import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import (
    Flask,
    abort,
    jsonify,
    render_template_string,
    request,
    send_from_directory,
)
from werkzeug.utils import secure_filename

from api_services import ApiService, DEFAULT_LLM_PROMPT_TEMPLATE, check_for_updates
from config_manager import ConfigManager
from version import CURRENT_VERSION


DEFAULT_OUTPUT_DIR_NAME = "output_reports"


def _ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _usage_snapshot(raw: Optional[Dict[str, Any]]) -> Dict[str, int]:
    raw = raw or {}
    return {
        "prompt_tokens": int(raw.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(raw.get("completion_tokens", 0) or 0),
    }


def create_app(config_manager: ConfigManager) -> Flask:
    """Create and configure the Flask web application."""

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB payload ceiling
    app.logger.handlers.clear()
    app.logger.propagate = True
    logger = logging.getLogger("essay_corrector.web")

    api_service = ApiService(config_manager)
    config_lock = threading.Lock()
    update_state: Dict[str, Optional[str]] = {"latest": None, "checked": None}
    update_lock = threading.Lock()
    run_states: Dict[str, Dict[str, Any]] = {}
    run_states_lock = threading.Lock()

    def get_output_root() -> Path:
        configured = config_manager.get("OutputDirectory")
        base_path = Path(configured) if configured else Path(DEFAULT_OUTPUT_DIR_NAME)
        if not base_path.is_absolute():
            base_path = Path.cwd() / base_path
        return _ensure_directory(base_path)

    def relative_to_output(path: Path) -> str:
        root = get_output_root().resolve()
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:  # pragma: no cover - safety guard
            raise ValueError("Requested path is outside of the output directory") from exc
        return relative.as_posix()

    def start_update_check(force: bool = False) -> None:
        if not _as_bool(config_manager.get("AutoUpdateCheck", True), True):
            return

        with update_lock:
            already_checked = update_state["checked"]

        if already_checked and not force:
            return

        def _worker() -> None:
            latest = check_for_updates(CURRENT_VERSION)
            timestamp = datetime.now().isoformat(timespec="seconds")
            with update_lock:
                update_state["latest"] = latest
                update_state["checked"] = timestamp

        threading.Thread(target=_worker, daemon=True).start()

    def _execute_run(
        run_id: str,
        saved_files: List[Dict[str, Any]],
        topic: str,
        run_dir: Path,
        max_workers: int,
        save_markdown: bool,
    ) -> None:
        aggregate = {"vlm_in": 0, "vlm_out": 0, "llm_in": 0, "llm_out": 0}
        failures = 0

        with run_states_lock:
            state = run_states.get(run_id)
            if state:
                state["status"] = "running"

        def process_single(file_info: Dict[str, Any]) -> Dict[str, Any]:
            saved_path: Path = file_info["path"]
            logs: List[str] = [f"开始处理: {file_info['original']}"]
            markdown_path: Optional[Path] = None
            html_path: Optional[Path] = None
            vlm_usage = {"prompt_tokens": 0, "completion_tokens": 0}
            llm_usage = {"prompt_tokens": 0, "completion_tokens": 0}
            error: Optional[str] = None
            rendered_html_path: Optional[str] = None

            report_markdown_path = saved_path.parent / f"{saved_path.stem}_report.md"

            try:
                final_report, raw_vlm_usage, raw_llm_usage, rendered_html_path = api_service.process_essay_image(
                    str(saved_path),
                    topic,
                )

                vlm_usage = _usage_snapshot(raw_vlm_usage)
                llm_usage = _usage_snapshot(raw_llm_usage)

                if save_markdown:
                    markdown_path = report_markdown_path
                    markdown_path.write_text(final_report, encoding="utf-8")
                    logs.append(f"已生成 Markdown: {markdown_path.name}")

                render_html = _as_bool(config_manager.get("RenderMarkdown", True), True)
                if rendered_html_path:
                    html_path = Path(rendered_html_path)
                    logs.append(f"已生成 HTML: {html_path.name}")
                    if not save_markdown and render_html and report_markdown_path.exists():
                        report_markdown_path.unlink(missing_ok=True)
                        logs.append("已删除 Markdown（仅保留 HTML）")
                elif not save_markdown and report_markdown_path.exists():
                    report_markdown_path.unlink(missing_ok=True)

                with config_lock:
                    config_manager.update_token_usage(
                        vlm_usage["prompt_tokens"],
                        vlm_usage["completion_tokens"],
                        llm_usage["prompt_tokens"],
                        llm_usage["completion_tokens"],
                    )
                    config_manager.save()

            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("文件处理失败: %s", saved_path)
                error = str(exc)
                logs.append(f"处理失败: {error}")

            saved_rel = relative_to_output(saved_path)
            markdown_rel = relative_to_output(markdown_path) if markdown_path else None
            if rendered_html_path:
                html_rel = relative_to_output(Path(rendered_html_path))
            else:
                html_rel = relative_to_output(html_path) if html_path else None

            return {
                "index": file_info["index"],
                "original": file_info["original"],
                "saved": saved_rel,
                "markdown": markdown_rel,
                "html": html_rel,
                "vlm_usage": vlm_usage,
                "llm_usage": llm_usage,
                "logs": logs,
                "error": error,
            }

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(process_single, info) for info in saved_files]
                for future in as_completed(futures):
                    result = future.result()
                    if not result["error"]:
                        aggregate["vlm_in"] += result["vlm_usage"]["prompt_tokens"]
                        aggregate["vlm_out"] += result["vlm_usage"]["completion_tokens"]
                        aggregate["llm_in"] += result["llm_usage"]["prompt_tokens"]
                        aggregate["llm_out"] += result["llm_usage"]["completion_tokens"]
                    else:
                        failures += 1

                    with run_states_lock:
                        state = run_states.get(run_id)
                        if not state:
                            continue
                        state["completed"] = state.get("completed", 0) + 1
                        state.setdefault("results", {})[result["index"]] = result
                        state["aggregate"] = aggregate.copy()
                        if result["error"]:
                            state.setdefault("errors", []).append(
                                {"index": result["index"], "message": result["error"]}
                            )
        except Exception as exc:  # pylint: disable=broad-except
            logging.exception("批处理任务失败: %s", run_id)
            with run_states_lock:
                state = run_states.get(run_id)
                if state:
                    state["status"] = "failed"
                    state["error"] = str(exc)
                    state["aggregate"] = aggregate
                    state["finished_at"] = datetime.now().isoformat(timespec="seconds")
            return

        total = len(saved_files)
        if total == 0:
            status = "empty"
        elif failures == 0:
            status = "ok"
        elif failures == total:
            status = "failed"
        else:
            status = "partial"

        with run_states_lock:
            state = run_states.get(run_id)
            if state:
                state["status"] = status
                state["aggregate"] = aggregate
                state["completed"] = total
                state["finished_at"] = datetime.now().isoformat(timespec="seconds")

    @app.get("/api/config")
    def read_config():
        usage = {
            "vlm_input": int(config_manager.get("UsageVlmInput", 0) or 0),
            "vlm_output": int(config_manager.get("UsageVlmOutput", 0) or 0),
            "llm_input": int(config_manager.get("UsageLlmInput", 0) or 0),
            "llm_output": int(config_manager.get("UsageLlmOutput", 0) or 0),
        }

        with update_lock:
            latest_version = update_state["latest"]
            checked_at = update_state["checked"]

        has_vlm_key = bool(config_manager.get("VlmApiKey"))
        has_llm_key = bool(config_manager.get("LlmApiKey"))

        data = {
            "VlmUrl": config_manager.get("VlmUrl", ""),
            "VlmApiKey": "",
            "HasVlmApiKey": has_vlm_key,
            "VlmModel": config_manager.get("VlmModel", ""),
            "VlmTemperature": config_manager.get("VlmTemperature", 0.0),
            "LlmUrl": config_manager.get("LlmUrl", ""),
            "LlmApiKey": "",
            "HasLlmApiKey": has_llm_key,
            "LlmModel": config_manager.get("LlmModel", ""),
            "LlmTemperature": config_manager.get("LlmTemperature", 0.0),
            "SensitivityFactor": config_manager.get("SensitivityFactor", "1.0"),
            "MaxWorkers": config_manager.get("MaxWorkers", 4),
            "MaxRetries": config_manager.get("MaxRetries", 3),
            "RetryDelay": config_manager.get("RetryDelay", 5),
            "RequestTimeout": config_manager.get("RequestTimeout", 120),
            "SaveMarkdown": _as_bool(config_manager.get("SaveMarkdown", True), True),
            "RenderMarkdown": _as_bool(config_manager.get("RenderMarkdown", True), True),
            "AutoUpdateCheck": _as_bool(config_manager.get("AutoUpdateCheck", True), True),
            "LlmPromptTemplate": config_manager.get("LlmPromptTemplate") or DEFAULT_LLM_PROMPT_TEMPLATE,
            "OutputDirectory": str(config_manager.get("OutputDirectory", DEFAULT_OUTPUT_DIR_NAME)),
            "Usage": usage,
            "CurrentVersion": CURRENT_VERSION,
            "LatestVersion": latest_version,
            "CheckedAt": checked_at,
        }
        return jsonify(data)

    @app.post("/api/config")
    def update_config():
        payload = request.get_json(silent=True) or {}

        string_fields = [
            "VlmUrl",
            "VlmModel",
            "LlmUrl",
            "LlmModel",
            "OutputDirectory",
        ]
        sensitive_fields = [
            "VlmApiKey",
            "LlmApiKey",
        ]
        int_fields = ["MaxWorkers", "MaxRetries", "RetryDelay"]
        float_fields = {
            "RequestTimeout": (1.0, None),
            "VlmTemperature": (0.0, 2.0),
            "LlmTemperature": (0.0, 2.0),
        }
        bool_fields = ["SaveMarkdown", "RenderMarkdown", "AutoUpdateCheck"]

        updates: Dict[str, Any] = {}

        for key in string_fields:
            if key in payload:
                value = (payload.get(key) or "").strip()
                if key == "OutputDirectory" and not value:
                    return jsonify({"error": "输出目录不能为空"}), 400
                updates[key] = value

        for key in sensitive_fields:
            if key in payload:
                value = (payload.get(key) or "").strip()
                if value:
                    updates[key] = value

        if payload.get("ClearVlmApiKey"):
            updates["VlmApiKey"] = ""
        if payload.get("ClearLlmApiKey"):
            updates["LlmApiKey"] = ""

        for key in int_fields:
            if key in payload and payload[key] not in (None, ""):
                try:
                    updates[key] = int(payload[key])
                except (TypeError, ValueError):
                    return jsonify({"error": f"{key} 需要是整数"}), 400

        for key, bounds in float_fields.items():
            if key in payload and payload[key] not in (None, ""):
                try:
                    value = float(payload[key])
                except (TypeError, ValueError):
                    return jsonify({"error": f"{key} 需要是数字"}), 400
                min_val, max_val = bounds
                if min_val is not None and value < min_val:
                    return jsonify({"error": f"{key} 不能小于 {min_val}"}), 400
                if max_val is not None and value > max_val:
                    return jsonify({"error": f"{key} 不能大于 {max_val}"}), 400
                updates[key] = value

        if "SensitivityFactor" in payload and payload["SensitivityFactor"] not in (None, ""):
            try:
                updates["SensitivityFactor"] = float(payload["SensitivityFactor"])
            except (TypeError, ValueError):
                return jsonify({"error": "SensitivityFactor 需要是数字"}), 400

        for key in bool_fields:
            if key in payload:
                updates[key] = bool(payload[key])

        prompt_template = payload.get("LlmPromptTemplate")
        if prompt_template is not None:
            normalized = str(prompt_template).strip()
            if not normalized:
                updates["LlmPromptTemplate"] = None
            elif normalized == DEFAULT_LLM_PROMPT_TEMPLATE.strip():
                updates["LlmPromptTemplate"] = None
            else:
                updates["LlmPromptTemplate"] = normalized

        with config_lock:
            for key, value in updates.items():
                if key == "LlmPromptTemplate" and value is None:
                    config_manager.config.pop(key, None)
                elif key in ("VlmApiKey", "LlmApiKey") and value == "":
                    config_manager.config.pop(key, None)
                else:
                    config_manager.set(key, value)
            config_manager.save()

        if "OutputDirectory" in updates and updates["OutputDirectory"]:
            get_output_root()

        start_update_check(force=True)
        return jsonify({"status": "ok"})

    @app.post("/api/process")
    def process_files():
        topic = (request.form.get("topic") or "").strip()
        if not topic:
            return jsonify({"error": "请输入作文题目"}), 400

        uploads = request.files.getlist("files")
        if not uploads:
            return jsonify({"error": "请至少选择一张图片"}), 400

        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_root = get_output_root()
        run_dir = _ensure_directory(output_root / run_id)

        saved_files: List[Dict[str, Any]] = []
        used_names = set()
        for index, upload in enumerate(uploads):
            original_name = upload.filename or f"upload_{index + 1}.png"
            safe_name = secure_filename(original_name) or f"upload_{index + 1}.png"
            if safe_name in used_names:
                stem = Path(safe_name).stem
                suffix = Path(safe_name).suffix or ".png"
                counter = 1
                candidate = f"{stem}_{counter}{suffix}"
                while candidate in used_names:
                    counter += 1
                    candidate = f"{stem}_{counter}{suffix}"
                safe_name = candidate
            used_names.add(safe_name)

            saved_path = run_dir / safe_name
            upload.save(saved_path)
            saved_files.append(
                {
                    "index": index,
                    "original": original_name,
                    "name": safe_name,
                    "path": saved_path,
                }
            )

        try:
            max_workers = int(config_manager.get("MaxWorkers", 4)) or 1
        except (TypeError, ValueError):
            max_workers = 4

        save_markdown = _as_bool(config_manager.get("SaveMarkdown", True), True)
        run_path = relative_to_output(run_dir)

        run_state = {
            "run_id": run_id,
            "status": "queued",
            "total": len(saved_files),
            "completed": 0,
            "aggregate": {"vlm_in": 0, "vlm_out": 0, "llm_in": 0, "llm_out": 0},
            "results": {},
            "errors": [],
            "run_path": run_path,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

        with run_states_lock:
            run_states[run_id] = run_state

        worker = threading.Thread(
            target=_execute_run,
            args=(run_id, saved_files, topic, run_dir, max_workers, save_markdown),
            daemon=True,
        )
        worker.start()

        return jsonify(
            {
                "status": "queued",
                "run_id": run_id,
                "total": len(saved_files),
                "run_path": run_path,
            }
        )

    @app.get("/api/run-status/<run_id>")
    def run_status(run_id: str):
        with run_states_lock:
            state = run_states.get(run_id)
            if not state:
                abort(404)

            results_dict = state.get("results", {})
            results = [results_dict[index] for index in sorted(results_dict.keys())]
            aggregate = dict(state.get("aggregate", {"vlm_in": 0, "vlm_out": 0, "llm_in": 0, "llm_out": 0}))

            response = {
                "run_id": run_id,
                "status": state.get("status", "unknown"),
                "total": state.get("total", 0),
                "completed": state.get("completed", 0),
                "aggregate": aggregate,
                "results": results,
                "run_path": state.get("run_path"),
                "error": state.get("error"),
                "errors": state.get("errors", []),
            }

        return jsonify(response)

    @app.get("/outputs/<path:requested_path>")
    def serve_outputs(requested_path: str):
        output_root = get_output_root().resolve()
        target_path = (output_root / requested_path).resolve()
        try:
            target_path.relative_to(output_root)
        except ValueError:
            abort(404)
        if not target_path.exists() or target_path.is_dir():
            abort(404)
        relative = target_path.relative_to(output_root).as_posix()
        return send_from_directory(str(output_root), relative)

    @app.get("/api/update-status")
    def update_status():
        with update_lock:
            return jsonify(
                {
                    "current": CURRENT_VERSION,
                    "latest": update_state["latest"],
                    "checked": update_state["checked"],
                }
            )

    @app.post("/api/update-check")
    def trigger_update_check():
        start_update_check(force=True)
        return jsonify({"status": "checking"})

    @app.get("/")
    def index():
        html = '''
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>AI 作文批改助手 · Web</title>
            <style>
                :root {
                    color-scheme: light;
                    --glass-bg: rgba(255, 255, 255, 0.28);
                    --glass-border: rgba(255, 255, 255, 0.45);
                    --text-dark: #101418;
                    --muted: rgba(16, 20, 24, 0.55);
                    --accent: rgba(52, 120, 246, 0.9);
                    --accent-strong: #0b61ff;
                }
                * {
                    box-sizing: border-box;
                }
                body {
                    margin: 0;
                    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: linear-gradient(135deg, #8ec5fc 0%, #e0c3fc 100%);
                    padding: 40px 16px;
                }
                .container {
                    width: min(1180px, 100%);
                    background: var(--glass-bg);
                    border-radius: 28px;
                    padding: 36px;
                    box-shadow: 0 25px 70px rgba(31, 38, 135, 0.25);
                    backdrop-filter: blur(26px);
                    border: 1px solid var(--glass-border);
                    color: var(--text-dark);
                    display: grid;
                    gap: 28px;
                }
                h1 {
                    margin: 0;
                    font-size: 30px;
                    font-weight: 600;
                }
                h2 {
                    margin: 0 0 18px;
                    font-size: 22px;
                    font-weight: 600;
                }
                p {
                    margin: 0;
                    color: var(--muted);
                }
                .top-bar {
                    display: flex;
                    flex-wrap: wrap;
                    justify-content: space-between;
                    gap: 16px;
                    align-items: center;
                }
                .title-block {
                    display: grid;
                    gap: 8px;
                }
                .pill {
                    padding: 7px 16px;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.55);
                    backdrop-filter: blur(12px);
                    font-size: 13px;
                    font-weight: 500;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    color: var(--muted);
                }
                .muted {
                    color: var(--muted);
                    font-size: 13px;
                }
                .nav {
                    display: flex;
                    gap: 12px;
                    flex-wrap: wrap;
                }
                .nav button {
                    border: none;
                    border-radius: 16px;
                    padding: 10px 20px;
                    background: rgba(255, 255, 255, 0.55);
                    color: var(--text-dark);
                    font-size: 15px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: background 0.2s ease, color 0.2s ease, transform 0.15s ease;
                }
                .nav button.active {
                    background: var(--accent);
                    color: #fff;
                    box-shadow: 0 12px 22px rgba(52, 120, 246, 0.25);
                }
                .nav button:hover {
                    transform: translateY(-1px);
                }
                .view {
                    display: none;
                    gap: 28px;
                }
                .view.active {
                    display: grid;
                }
                .section {
                    display: grid;
                    gap: 20px;
                }
                form {
                    display: grid;
                    gap: 18px;
                    background: rgba(255, 255, 255, 0.45);
                    border-radius: 24px;
                    padding: 24px;
                    border: 1px solid rgba(255, 255, 255, 0.4);
                    backdrop-filter: blur(10px);
                }
                .grid-2 {
                    display: grid;
                    gap: 18px;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                }
                label {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    font-size: 14px;
                    font-weight: 500;
                    color: rgba(16, 20, 24, 0.85);
                }
                input[type="text"],
                input[type="number"],
                textarea {
                    border-radius: 14px;
                    border: 1px solid rgba(255, 255, 255, 0.6);
                    padding: 12px 14px;
                    font-size: 15px;
                    background: rgba(255, 255, 255, 0.65);
                    color: var(--text-dark);
                    outline: none;
                    transition: border 0.2s ease, box-shadow 0.2s ease;
                }
                input:focus,
                textarea:focus {
                    border-color: var(--accent);
                    box-shadow: 0 0 0 3px rgba(52, 120, 246, 0.15);
                }
                textarea {
                    min-height: 120px;
                    resize: vertical;
                }
                .checkbox-row {
                    display: flex;
                    gap: 12px;
                    align-items: center;
                }
                .checkbox-row input {
                    width: 18px;
                    height: 18px;
                }
                .actions {
                    display: flex;
                    gap: 14px;
                    flex-wrap: wrap;
                }
                button {
                    border: none;
                    border-radius: 14px;
                    padding: 12px 22px;
                    font-size: 15px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: transform 0.15s ease, box-shadow 0.15s ease;
                    background: rgba(52, 120, 246, 0.9);
                    color: #fff;
                }
                button:hover {
                    transform: translateY(-1px);
                    box-shadow: 0 12px 22px rgba(52, 120, 246, 0.25);
                }
                button:disabled {
                    opacity: 0.55;
                    cursor: not-allowed;
                    box-shadow: none;
                }
                .ghost-btn {
                    background: transparent;
                    color: var(--text-dark);
                    border: 1px solid rgba(255, 255, 255, 0.55);
                }
                .results {
                    display: grid;
                    gap: 18px;
                }
                .result-card {
                    border-radius: 20px;
                    padding: 20px;
                    background: rgba(255, 255, 255, 0.55);
                    backdrop-filter: blur(18px);
                    border: 1px solid rgba(255, 255, 255, 0.45);
                    display: grid;
                    gap: 12px;
                }
                .result-card.error {
                    border-color: rgba(255, 99, 132, 0.45);
                    background: rgba(255, 245, 247, 0.75);
                }
                .result-card.success {
                    border-color: rgba(72, 199, 142, 0.45);
                }
                .result-header {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 12px;
                    align-items: center;
                    justify-content: space-between;
                }
                .result-links {
                    display: flex;
                    gap: 12px;
                    flex-wrap: wrap;
                }
                .result-links a {
                    font-size: 13px;
                    font-weight: 600;
                    color: var(--accent-strong);
                    text-decoration: none;
                }
                .logs {
                    font-size: 13px;
                    color: rgba(16, 20, 24, 0.7);
                    line-height: 1.5;
                }
                .banner {
                    display: flex;
                    gap: 12px;
                    align-items: center;
                    padding: 14px 16px;
                    border-radius: 16px;
                    background: rgba(255, 255, 255, 0.6);
                    border: 1px solid rgba(255, 255, 255, 0.45);
                    font-size: 14px;
                }
                .about-card {
                    border-radius: 20px;
                    padding: 24px;
                    background: rgba(255, 255, 255, 0.55);
                    border: 1px solid rgba(255, 255, 255, 0.45);
                    backdrop-filter: blur(18px);
                    display: grid;
                    gap: 16px;
                    line-height: 1.6;
                }
                ul {
                    margin: 0;
                    padding-left: 20px;
                    color: var(--muted);
                }
                code {
                    background: rgba(16, 20, 24, 0.08);
                    border-radius: 6px;
                    padding: 2px 6px;
                    font-size: 13px;
                }
                #toast {
                    position: fixed;
                    bottom: 24px;
                    right: 24px;
                    padding: 14px 18px;
                    border-radius: 14px;
                    background: rgba(16, 20, 24, 0.85);
                    color: #fff;
                    font-size: 14px;
                    opacity: 0;
                    transform: translateY(12px);
                    pointer-events: none;
                    transition: opacity 0.2s ease, transform 0.2s ease;
                }
                #toast.show {
                    opacity: 1;
                    transform: translateY(0);
                }
                @media (max-width: 820px) {
                    .container {
                        padding: 26px;
                    }
                    form {
                        padding: 20px;
                    }
                    .result-header {
                        flex-direction: column;
                        align-items: flex-start;
                    }
                    .nav button {
                        flex: 1 1 120px;
                    }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="top-bar">
                    <div class="title-block">
                        <h1>AI 作文批改助手 · Web</h1>
                        <p id="version-info">版本 {{ current_version }}</p>
                    </div>
                    <div class="pill" id="usage-pill">加载用量中...</div>
                </div>

                <div class="nav">
                    <button class="nav-btn active" data-view="grading">批改作文</button>
                    <button class="nav-btn" data-view="settings">服务设置</button>
                    <button class="nav-btn" data-view="about">关于</button>
                </div>

                <div class="view active" data-view-section="grading">
                    <div class="section">
                        <h2>批改任务</h2>
                        <form id="process-form" enctype="multipart/form-data">
                            <label>作文题目 / 场景说明
                                <textarea name="topic" placeholder="请粘贴题目或场景描述"></textarea>
                            </label>
                            <label>上传作文照片 (支持多选)
                                <input type="file" name="files" accept="image/*" multiple />
                            </label>
                            <div class="actions">
                                <button type="submit" id="start-process">开始批改</button>
                            </div>
                        </form>
                        <div id="process-status"></div>
                    </div>

                    <div class="section">
                        <h2>批改结果</h2>
                        <div id="results" class="results">
                            <div class="banner">暂时没有任务，上传图片后将显示处理结果。</div>
                        </div>
                    </div>
                </div>

                <div class="view" data-view-section="settings">
                    <div class="section">
                        <h2>服务设置</h2>
                        <form id="settings-form">
                            <div class="grid-2">
                                <label>VLM URL
                                    <input type="text" name="vlm_url" autocomplete="off" />
                                </label>
                                <label>VLM API Key
                                    <input type="text" name="vlm_api_key" autocomplete="off" />
                                </label>
                                <label>VLM 模型
                                    <input type="text" name="vlm_model" autocomplete="off" />
                                </label>
                                <label>VLM 温度 (0-2)
                                    <input type="number" name="vlm_temperature" min="0" max="2" step="0.1" />
                                </label>
                                <label>LLM URL
                                    <input type="text" name="llm_url" autocomplete="off" />
                                </label>
                                <label>LLM API Key
                                    <input type="text" name="llm_api_key" autocomplete="off" />
                                </label>
                                <label>LLM 模型
                                    <input type="text" name="llm_model" autocomplete="off" />
                                </label>
                                <label>LLM 温度 (0-2)
                                    <input type="number" name="llm_temperature" min="0" max="2" step="0.1" />
                                </label>
                                <label>手写敏感度 (建议 1.0)
                                    <input type="text" name="sensitivity_factor" autocomplete="off" />
                                </label>
                                <label>最大并发数
                                    <input type="number" name="max_workers" min="1" />
                                </label>
                                <label>最大重试次数
                                    <input type="number" name="max_retries" min="1" />
                                </label>
                                <label>重试延迟 (秒)
                                    <input type="number" name="retry_delay" min="1" />
                                </label>
                                <label>请求超时时间 (秒)
                                    <input type="number" name="request_timeout" min="1" step="1" />
                                </label>
                                <label>输出目录
                                    <input type="text" name="output_directory" autocomplete="off" />
                                </label>
                            </div>
                            <div class="grid-2">
                                <label class="checkbox-row"><input type="checkbox" name="save_markdown" />保存 Markdown</label>
                                <label class="checkbox-row"><input type="checkbox" name="render_markdown" />渲染 HTML 报告</label>
                                <label class="checkbox-row"><input type="checkbox" name="auto_update_check" />启动时检查更新</label>
                            </div>
                            <label>LLM Prompt 模板
                                <textarea name="llm_prompt" spellcheck="false"></textarea>
                            </label>
                            <div class="actions">
                                <button type="submit" id="save-settings">保存设置</button>
                                <button type="button" id="reset-template" class="ghost-btn">恢复默认模板</button>
                            </div>
                        </form>
                    </div>
                </div>

                <div class="view" data-view-section="about">
                    <div class="section">
                        <h2>关于与更新</h2>
                        <div class="about-card">
                            <h3>AI 作文批改助手</h3>
                            <p>一款专注于英语作文批改的 Web 应用，整合视觉语言模型（VLM）与大语言模型（LLM），帮助教师与学生高效获得结构化反馈。</p>
                            <ul>
                                <li>两阶段流水线：先识别手写文本与书写分，再生成全中文批改报告。</li>
                                <li>任务分离：所有图片自动归档到独立 run id，方便回溯、分享与比对。</li>
                                <li>Prompt 可编辑：浏览器内直接替换评分模板，快速适配不同考试场景。</li>
                                <li>安全可控：API Key 本地加密保存，Token 用量实时累计并在界面呈现。</li>
                            </ul>
                            <p class="muted">作者：Eric_Terminal · 项目主页：<a href="https://github.com/Eric-Terminal/Pro_llm_correct" target="_blank" rel="noopener">GitHub</a></p>
                        </div>
                        <div class="about-card">
                            <div><strong>当前版本：</strong><span id="about-current">{{ current_version }}</span></div>
                            <div id="about-latest">正在获取最新版本信息...</div>
                            <div id="about-checked" class="muted"></div>
                            <div class="actions">
                                <button class="ghost-btn" id="check-updates">检查更新</button>
                            </div>
                        </div>
                        <div class="about-card">
                            <strong>使用提示</strong>
                            <ul>
                                <li>默认使用 <code>output_reports/时间戳</code> 保存批改文件，可在设置中修改。</li>
                                <li>可单独保存 Markdown 或 HTML，也可保留二者。</li>
                                <li>Prompt 模板支持完全自定义，请保留参数占位符以确保正常传值。</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
            <div id="toast"></div>
            <script>
                const navButtons = document.querySelectorAll('.nav-btn');
                const views = document.querySelectorAll('[data-view-section]');
                const settingsForm = document.getElementById('settings-form');
                const processForm = document.getElementById('process-form');
                const fileInput = processForm.querySelector('input[name="files"]');
                const startButton = document.getElementById('start-process');
                const resultsPanel = document.getElementById('results');
                const statusBox = document.getElementById('process-status');
                const toast = document.getElementById('toast');
                const usagePill = document.getElementById('usage-pill');
                const versionInfo = document.getElementById('version-info');
                const resetTemplateBtn = document.getElementById('reset-template');
                const checkUpdatesBtn = document.getElementById('check-updates');
                const aboutCurrent = document.getElementById('about-current');
                const aboutLatest = document.getElementById('about-latest');
                const aboutChecked = document.getElementById('about-checked');
                let pollTimer = null;
                let currentRunId = null;

                function switchView(view) {
                    views.forEach((section) => {
                        section.classList.toggle('active', section.dataset.viewSection === view);
                    });
                    navButtons.forEach((btn) => {
                        btn.classList.toggle('active', btn.dataset.view === view);
                    });
                }

                navButtons.forEach((btn) => {
                    btn.addEventListener('click', () => switchView(btn.dataset.view));
                });

                function showToast(message, type = 'info') {
                    toast.textContent = message;
                    toast.classList.add('show');
                    if (type === 'error') {
                        toast.style.background = 'rgba(220, 53, 69, 0.9)';
                    } else if (type === 'success') {
                        toast.style.background = 'rgba(46, 204, 113, 0.9)';
                    } else {
                        toast.style.background = 'rgba(16, 20, 24, 0.85)';
                    }
                    setTimeout(() => toast.classList.remove('show'), 2800);
                }

                function stopPolling() {
                    if (pollTimer) {
                        clearInterval(pollTimer);
                        pollTimer = null;
                    }
                }

                function updateAboutInfo(data) {
                    aboutCurrent.textContent = data.CurrentVersion;
                    if (data.LatestVersion && data.LatestVersion !== data.CurrentVersion) {
                        aboutLatest.textContent = `发现新版本 ${data.LatestVersion}`;
                    } else if (data.LatestVersion) {
                        aboutLatest.textContent = '当前已是最新版本。';
                    } else {
                        aboutLatest.textContent = '尚未检测到新版本。';
                    }
                    aboutChecked.textContent = data.CheckedAt ? `最近检查：${data.CheckedAt}` : '';
                }

                function populateConfig(data) {
                    settingsForm.vlm_url.value = data.VlmUrl || '';
                    settingsForm.vlm_api_key.value = '';
                    settingsForm.vlm_model.value = data.VlmModel || '';
                    settingsForm.vlm_temperature.value = data.VlmTemperature ?? 0;
                    settingsForm.llm_url.value = data.LlmUrl || '';
                    settingsForm.llm_api_key.value = '';
                    settingsForm.llm_model.value = data.LlmModel || '';
                    settingsForm.llm_temperature.value = data.LlmTemperature ?? 0;
                    settingsForm.sensitivity_factor.value = data.SensitivityFactor || '';
                    settingsForm.max_workers.value = data.MaxWorkers || 4;
                    settingsForm.max_retries.value = data.MaxRetries || 3;
                    settingsForm.retry_delay.value = data.RetryDelay || 5;
                    settingsForm.request_timeout.value = data.RequestTimeout ?? 120;
                    settingsForm.output_directory.value = data.OutputDirectory || '{{ default_output_dir }}';
                    settingsForm.save_markdown.checked = !!data.SaveMarkdown;
                    settingsForm.render_markdown.checked = !!data.RenderMarkdown;
                    settingsForm.auto_update_check.checked = !!data.AutoUpdateCheck;
                    settingsForm.llm_prompt.value = data.LlmPromptTemplate || '';

                    usagePill.textContent = `VLM ${data.Usage.vlm_input}/${data.Usage.vlm_output} · LLM ${data.Usage.llm_input}/${data.Usage.llm_output}`;

                    const hasVlmKey = !!data.HasVlmApiKey;
                    const hasLlmKey = !!data.HasLlmApiKey;

                    if (hasVlmKey) {
                        settingsForm.vlm_api_key.placeholder = '已保存 · 输入新密钥以更新';
                        settingsForm.vlm_api_key.dataset.saved = 'true';
                        settingsForm.vlm_api_key.title = '已保存，留空保持不变';
                    } else {
                        settingsForm.vlm_api_key.placeholder = '';
                        delete settingsForm.vlm_api_key.dataset.saved;
                        settingsForm.vlm_api_key.removeAttribute('title');
                    }

                    if (hasLlmKey) {
                        settingsForm.llm_api_key.placeholder = '已保存 · 输入新密钥以更新';
                        settingsForm.llm_api_key.dataset.saved = 'true';
                        settingsForm.llm_api_key.title = '已保存，留空保持不变';
                    } else {
                        settingsForm.llm_api_key.placeholder = '';
                        delete settingsForm.llm_api_key.dataset.saved;
                        settingsForm.llm_api_key.removeAttribute('title');
                    }

                    if (data.LatestVersion && data.LatestVersion !== data.CurrentVersion) {
                        versionInfo.textContent = `版本 ${data.CurrentVersion} · 发现新版本 ${data.LatestVersion}`;
                    } else {
                        versionInfo.textContent = `版本 ${data.CurrentVersion}`;
                    }
                    updateAboutInfo(data);
                }

                async function loadConfig() {
                    try {
                        const res = await fetch('/api/config');
                        if (!res.ok) throw new Error(await res.text());
                        const data = await res.json();
                        populateConfig(data);
                    } catch (err) {
                        console.error(err);
                        showToast('加载配置失败', 'error');
                    }
                }

                settingsForm.addEventListener('submit', async (event) => {
                    event.preventDefault();
                    const payload = {
                        VlmUrl: settingsForm.vlm_url.value.trim(),
                        VlmApiKey: settingsForm.vlm_api_key.value.trim(),
                        VlmModel: settingsForm.vlm_model.value.trim(),
                        VlmTemperature: settingsForm.vlm_temperature.value,
                        LlmUrl: settingsForm.llm_url.value.trim(),
                        LlmApiKey: settingsForm.llm_api_key.value.trim(),
                        LlmModel: settingsForm.llm_model.value.trim(),
                        LlmTemperature: settingsForm.llm_temperature.value,
                        SensitivityFactor: settingsForm.sensitivity_factor.value.trim(),
                        MaxWorkers: settingsForm.max_workers.value,
                        MaxRetries: settingsForm.max_retries.value,
                        RetryDelay: settingsForm.retry_delay.value,
                        RequestTimeout: settingsForm.request_timeout.value,
                        OutputDirectory: settingsForm.output_directory.value.trim(),
                        SaveMarkdown: settingsForm.save_markdown.checked,
                        RenderMarkdown: settingsForm.render_markdown.checked,
                        AutoUpdateCheck: settingsForm.auto_update_check.checked,
                        LlmPromptTemplate: settingsForm.llm_prompt.value,
                    };
                    try {
                        const res = await fetch('/api/config', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload),
                        });
                        if (!res.ok) {
                            const data = await res.json().catch(() => ({}));
                            throw new Error(data.error || '保存失败');
                        }
                        showToast('设置已保存', 'success');
                        loadConfig();
                    } catch (err) {
                        showToast(err.message, 'error');
                    }
                });

                resetTemplateBtn.addEventListener('click', () => {
                    fetch('/api/config')
                        .then((res) => res.json())
                        .then((data) => {
                            settingsForm.llm_prompt.value = data.LlmPromptTemplate;
                            showToast('已恢复默认模板');
                        })
                        .catch(() => showToast('恢复失败', 'error'));
                });

                processForm.addEventListener('submit', async (event) => {
                    event.preventDefault();
                    if (pollTimer) {
                        showToast('上一个任务仍在进行，请稍候', 'error');
                        return;
                    }

                    const formData = new FormData(processForm);
                    if (!(formData.get('topic') || '').trim()) {
                        showToast('请填写作文题目', 'error');
                        return;
                    }
                    if (!fileInput.files.length) {
                        showToast('请至少选择一张图片', 'error');
                        return;
                    }

                    startButton.disabled = true;
                    statusBox.textContent = '正在排队...';
                    resultsPanel.innerHTML = '<div class="banner">任务已提交，正在排队...</div>';

                    try {
                        const res = await fetch('/api/process', {
                            method: 'POST',
                            body: formData,
                        });

                        if (!res.ok) {
                            startButton.disabled = false;
                            const data = await res.json().catch(() => ({}));
                            throw new Error(data.error || '处理失败');
                        }

                        const data = await res.json();
                        if (!data.run_id) {
                            startButton.disabled = false;
                            throw new Error('任务启动失败');
                        }

                        statusBox.textContent = `正在批改：已完成 0 / ${data.total || 0}`;
                        renderResults({
                            status: 'queued',
                            total: data.total || 0,
                            completed: 0,
                            results: [],
                            aggregate: { vlm_in: 0, vlm_out: 0, llm_in: 0, llm_out: 0 },
                            run_path: data.run_path,
                        });
                        startPolling(data.run_id);
                    } catch (err) {
                        showToast(err.message, 'error');
                        statusBox.textContent = '';
                        startButton.disabled = false;
                    }
                });

                function startPolling(runId) {
                    currentRunId = runId;
                    stopPolling();
                    pollRunStatus();
                    pollTimer = setInterval(pollRunStatus, 1500);
                }

                async function pollRunStatus() {
                    if (!currentRunId) {
                        return;
                    }
                    try {
                        const res = await fetch(`/api/run-status/${currentRunId}`);
                        if (!res.ok) {
                            throw new Error(await res.text());
                        }
                        const data = await res.json();
                        const total = data.total || 0;
                        const completed = data.completed || 0;

                        if (data.status === 'queued' || data.status === 'running') {
                            statusBox.textContent = `正在批改：已完成 ${completed} / ${total}`;
                            renderResults(data);
                        } else {
                            stopPolling();
                            currentRunId = null;
                            startButton.disabled = false;

                            if (data.status === 'ok') {
                                statusBox.textContent = '任务完成';
                                showToast('任务完成', 'success');
                            } else if (data.status === 'partial') {
                                statusBox.textContent = '任务部分失败';
                                showToast('部分文件处理失败', 'error');
                            } else if (data.status === 'failed') {
                                statusBox.textContent = '任务失败';
                                showToast(data.error || '任务失败', 'error');
                            } else if (data.status === 'empty') {
                                statusBox.textContent = '无可处理的文件';
                                showToast('没有可处理的文件', 'info');
                            } else {
                                statusBox.textContent = '任务完成';
                            }

                            renderResults(data);
                            loadConfig();
                        }
                    } catch (err) {
                        console.error(err);
                        showToast('获取进度失败', 'error');
                        stopPolling();
                        startButton.disabled = false;
                        currentRunId = null;
                    }
                }

                function renderResults(data) {
                    const status = data.status || 'running';
                    const total = data.total || 0;
                    const completed = data.completed || 0;
                    const results = Array.isArray(data.results) ? data.results : [];
                    const aggregate = data.aggregate || {};
                    const statusMap = {
                        queued: '排队中',
                        running: '处理中',
                        ok: '完成',
                        partial: '部分完成',
                        failed: '失败',
                        empty: '无结果',
                    };
                    const locationNote = data.run_path ? ` · 输出目录 ${data.run_path}` : '';
                    const summary = `${statusMap[status] || status} · 已完成 ${completed}/${total}${locationNote}`;
                    const aggLine = `合计 | VLM ${aggregate.vlm_in || 0}/${aggregate.vlm_out || 0} · LLM ${aggregate.llm_in || 0}/${aggregate.llm_out || 0}`;

                    let content = `<div class="banner">${summary}</div><div class="banner">${aggLine}</div>`;

                    if (!results.length) {
                        content += '<div class="banner">暂无结果，请稍候...</div>';
                        resultsPanel.innerHTML = content;
                        return;
                    }

                    const cards = results
                        .map((item) => {
                            const statusClass = item.error ? 'result-card error' : 'result-card success';
                            const links = [];
                            if (item.saved) {
                                links.push(`<a href="/outputs/${item.saved}" target="_blank">原图</a>`);
                            }
                            if (item.markdown) {
                                links.push(`<a href="/outputs/${item.markdown}" target="_blank">Markdown</a>`);
                            }
                            if (item.html) {
                                links.push(`<a href="/outputs/${item.html}" target="_blank">HTML</a>`);
                            }
                            const usage = `VLM ${item.vlm_usage.prompt_tokens}/${item.vlm_usage.completion_tokens} · LLM ${item.llm_usage.prompt_tokens}/${item.llm_usage.completion_tokens}`;
                            const logLines = (item.logs || []).map((log) => `<div>• ${log}</div>`).join('');
                            const errorBlock = item.error ? `<strong style="color:#d93025;">${item.error}</strong>` : '';
                            return `
                                <div class="${statusClass}">
                                    <div class="result-header">
                                        <div>
                                            <strong>${item.original}</strong>
                                            <div style="font-size:12px;color:rgba(16,20,24,0.55);">${usage}</div>
                                        </div>
                                        <div class="result-links">${links.join('')}</div>
                                    </div>
                                    <div class="logs">${errorBlock}${logLines}</div>
                                </div>
                            `;
                        })
                        .join('');

                    resultsPanel.innerHTML = content + cards;
                }

                async function refreshUpdateStatus(showToastOnNew = false) {
                    try {
                        const res = await fetch('/api/update-status');
                        if (!res.ok) return;
                        const data = await res.json();
                        if (data.current) {
                            versionInfo.textContent = `版本 ${data.current}`;
                            aboutCurrent.textContent = data.current;
                        }
                        if (data.latest && data.latest !== data.current) {
                            versionInfo.textContent = `版本 ${data.current} · 发现新版本 ${data.latest}`;
                            aboutLatest.textContent = `发现新版本 ${data.latest}`;
                            if (showToastOnNew) {
                                showToast(`发现新版本 ${data.latest}`, 'success');
                            }
                        } else if (data.latest) {
                            aboutLatest.textContent = '当前已是最新版本。';
                        } else {
                            aboutLatest.textContent = '尚未检测到新版本。';
                        }
                        if (data.checked) {
                            aboutChecked.textContent = `最近检查：${data.checked}`;
                        }
                    } catch (err) {
                        console.warn('更新检查失败', err);
                    }
                }

                checkUpdatesBtn.addEventListener('click', async () => {
                    try {
                        await fetch('/api/update-check', { method: 'POST' });
                        showToast('正在检查更新...');
                        setTimeout(() => refreshUpdateStatus(true), 2000);
                    } catch (err) {
                        showToast('检查失败', 'error');
                    }
                });

                switchView('grading');
                loadConfig().then(() => refreshUpdateStatus());
            </script>
        </body>
        </html>
        '''
        return render_template_string(
            html,
            current_version=CURRENT_VERSION,
            default_output_dir=DEFAULT_OUTPUT_DIR_NAME,
        )

    start_update_check()
    return app
