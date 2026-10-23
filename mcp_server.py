from mcp.server.fastmcp import FastMCP

from tools.weather import get_weather
from tools.image_to_pdf import images_to_pdf

mcp = FastMCP(
    name="My Python MCP Server",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
)

@mcp.tool()
def weather_tool(city: str) -> dict:
    """Get current weather for a city."""
    return get_weather(city)

@mcp.tool()
def image_to_pdf_tool(images_base64: list[str]) -> dict:
    """Convert base64-encoded images into a PDF."""
    return images_to_pdf(images_base64)
