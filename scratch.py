import json
import requests


def bgg_query(query):
    return requests.get(
        "https://boardgamegeek.com/search/boardgame",
        params={
            "q": query,
            "nosession": 1,
            "showcount": 5,
        },
        headers={
            "Accept": "application/json",
        },
    )


def _items(res):
    res.raise_for_status()
    return res.json().get("items")
