
import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def get_weather(city: str) -> dict:
    city = city.strip()

    if not city or len(city) > 100:
        raise ValueError("Provide a valid city name.")

    location_response = requests.get(
        GEOCODING_URL,
        params={"name": city, "count": 1},
        timeout=15,
    )
    location_response.raise_for_status()

    locations = location_response.json().get("results", [])

    if not locations:
        raise ValueError(f"City not found: {city}")

    location = locations[0]

    response = requests.get(
        WEATHER_URL,
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": (
                "temperature_2m,relative_humidity_2m,"
                "apparent_temperature,weather_code,"
                "wind_speed_10m"
            ),
            "timezone": "auto",
        },
        timeout=15,
    )
    response.raise_for_status()

    current = response.json()["current"]
    code = current["weather_code"]

    return {
        "city": location["name"],
        "country": location.get("country"),
        "time": current["time"],
        "temperature_c": current["temperature_2m"],
        "feels_like_c": current["apparent_temperature"],
        "humidity_percent": current["relative_humidity_2m"],
        "wind_speed_kmh": current["wind_speed_10m"],
        "condition": WEATHER_CODES.get(code, "Unknown"),
        "weather_code": code,
        "source": "Open-Meteo",
    }
