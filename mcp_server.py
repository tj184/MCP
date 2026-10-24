
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from tools.weather import get_weather
from tools.image_to_pdf import images_to_pdf
from reminder_tools import create_reminder


security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "mcp-xkf4.onrender.com",
        "mcp-xkf4.onrender.com:*",
    ],
)

mcp = FastMCP(
    name="My Python MCP Server",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
    transport_security=security,
)


@mcp.tool()
def weather_tool(city: str) -> dict:
    """Get current weather for a city."""
    return get_weather(city)

@mcp.tool()
def schedule_phone_reminder(
    message: str,
    scheduled_at: str
) -> dict:
    """
    Schedule a Telegram reminder.

    scheduled_at must be an ISO 8601 timestamp
    with timezone offset, for example:
    2026-10-25T08:00:00+05:30
    """
    return create_reminder(message, scheduled_at)


@mcp.tool()
def image_to_pdf_tool(images_base64: list[str]) -> dict:
    """Convert base64-encoded images to one PDF."""
    return images_to_pdf(images_base64)
