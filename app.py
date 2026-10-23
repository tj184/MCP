
import os
import io
import base64
from contextlib import asynccontextmanager

from flask import Flask, jsonify, request, send_file
from starlette.applications import Starlette
from starlette.middleware.wsgi import WSGIMiddleware
from starlette.routing import Mount

from mcp_server import mcp
from tools.weather import get_weather
from utils.pdf_utils import create_pdf

flask_app = Flask(__name__)
flask_app.config["MAX_CONTENT_LENGTH"] = 70 * 1024 * 1024


@flask_app.get("/")
def home():
    return jsonify({
        "name": "My Python MCP Server",
        "status": "running",
        "mcp_endpoint": "/mcp",
        "tools": ["weather_tool", "image_to_pdf_tool"],
    })


@flask_app.get("/health")
def health():
    return jsonify({"status": "ok"})


@flask_app.get("/api/weather")
def weather_api():
    city = request.args.get("city", "").strip()

    if not city:
        return jsonify({"error": "city is required"}), 400

    try:
        return jsonify(get_weather(city))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        flask_app.logger.exception("Weather API failed")
        return jsonify({"error": "Weather service unavailable"}), 502


@flask_app.post("/api/image-to-pdf")
def pdf_api():
    uploaded = request.files.getlist("images")

    if not uploaded:
        return jsonify({"error": "Upload images using the 'images' field"}), 400

    if len(uploaded) > 10:
        return jsonify({"error": "Maximum 10 images"}), 400

    try:
        encoded_images = [
            base64.b64encode(file.read()).decode("ascii")
            for file in uploaded
        ]

        pdf_bytes = create_pdf(encoded_images)

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="converted.pdf",
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    host="0.0.0.0",
)

@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield

app = Starlette(
    routes=[
        *mcp_app.routes,
        Mount("/", app=WSGIMiddleware(flask_app)),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
