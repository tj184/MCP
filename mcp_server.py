
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
    """
    Get current weather for a city.

    Args:
        city: City name, for example Bengaluru or London.
    """
    return get_weather(city)


@mcp.tool()
def image_to_pdf_tool(images_base64: list[str]) -> dict:
    """
    Convert 1-10 base64-encoded images to one PDF.

    Returns a base64-encoded PDF and metadata.
    The MCP client must decode the returned PDF.
    """
    return images_to_pdf(images_base64)
