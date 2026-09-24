from dataclasses import dataclass


@dataclass
class SearchQuery:
    search_type: str
    category: str
    location: str
    query: str
    source: str | None = None
    venue: str | None = None

MAJOR_CITIES = [
    "Jyväskylä",
    "Lahti",
    "Mikkeli",
    "Pieksämäki",
    "Jämsä",
    "Heinola",
]


GENERAL_SEARCHES_MAJOR = [
    {
        "type": "music",
        "query": lambda city, start, end:
            f'"{city}" Finland '
            f"(keikat OR konsertti OR konsertit OR live-musiikki OR "
            f"live music OR gigs OR concert OR concerts) "
            f"{start} {end}",
    },
    {
        "type": "culture",
        "query": lambda city, start, end:
            f'"{city}" Finland '
            f"(tapahtumat OR tapahtuma OR kulttuuri OR teatteri OR "
            f"näyttely OR museo OR kirjallisuus) "
            f"{start} {end}",
    },
    {
        "type": "small_events",
        "query": lambda city, start, end:
            f'"{city}" Finland '
            f"(pub OR baari OR club OR klubi OR ravintola OR "
            f"live OR keikka OR DJ OR stand-up OR comedy) "
            f"{start} {end}",
    },
    {
        "type": "general_events",
        "query": lambda city, start, end:
            f'"{city}" Finland '
            f"(festival OR festivaali OR markkinat OR messut OR "
            f"ulkoilmatapahtuma OR puisto OR perhe OR luento OR "
            f"keskustelu OR tapahtuma) "
            f"{start} {end}",
    },
]

GENERAL_SEARCHES_SMALL = [
    {
        "type": "events",
        "query": lambda city, start, end:
            f'"{city}" Finland '
            f"(tapahtumat OR keikat OR konsertit OR kulttuuri OR "
            f"teatteri OR festivaali OR markkinat OR messut) "
            f"{start} {end}",
    },
    {
        "type": "local_events",
        "query": lambda city, start, end:
            f'"{city}" Finland '
            f"(pub OR baari OR ravintola OR klubi OR "
            f"live OR tapahtuma OR ulkoilma OR puisto OR "
            f"perhe OR kylä) "
            f"{start} {end}",
    },
]

LOCATIONS = [
    "Joutsa",
    "Jyväskylä",
    "Lahti",
    "Mikkeli",
    "Jämsä",
    "Heinola",
    "Pieksämäki",
    "Keuruu",
    "Hartola",
    "Sysmä",
    "Luhanka",
    "Toivakka",
    "Korpilahti",
    "Säynätsalo",
    "Pertunmaa",
    "Hirvensalmi",
    "Kangasniemi",
    "Mäntyharju",
    "Äänekoski",
    "Suonenjoki",
]

AGGREGATOR_CITIES = [
    "Jyväskylä",
    "Lahti",
    "Mikkeli",
    "Pieksämäki",
    "Jämsä",
    "Keuruu",
]


AGGREGATORS = [
    {
        "name": "Keikkalista",
        "domain": "keikkalista.fi",
        "keywords": "keikat konsertit live musiikki",
    },
    {
        "name": "Keikat.live",
        "domain": "keikat.live",
        "keywords": "keikat konsertit tapahtumat",
    },
    {
        "name": "Mitä Menoa",
        "domain": "mitamenoa.fi",
        "keywords": "konsertit tapahtumat kulttuuri",
    },
]

STANDUP_CITIES = [
    "Jyväskylä",
    "Lahti",
    "Mikkeli",
    "Pieksämäki",
    "Jämsä",
    "Heinola",
]


STANDUP_SOURCES = [
    {
        "name": "Nauramaan",
        "domain": "nauramaan.com",
    },
    {
        "name": "Stand Up Finland",
        "domain": "standup.fi",
    },
]

OFFICIAL_SOURCES = [
    {
        "city": "Jyväskylä",
        "name": "Visit Jyväskylä",
        "query": lambda start, end:
            f"site:visitjyvaskyla.fi "
            f"Jyväskylä tapahtumat "
            f"{start} {end}",
    },
    {
        "city": "Jyväskylä",
        "name": "Jyväskylä city",
        "query": lambda start, end:
            f"site:jkl.fi "
            f"Jyväskylä tapahtumat kulttuuri "
            f"{start} {end}",
    },
    {
        "city": "Lahti",
        "name": "Visit Lahti",
        "query": lambda start, end:
            f"site:visitlahti.fi "
            f"Lahti tapahtumat "
            f"{start} {end}",
    },
    {
        "city": "Lahti",
        "name": "Sibeliustalo",
        "query": lambda start, end:
            f"site:sibeliustalo.fi "
            f"Lahti tapahtumat konsertti teatteri "
            f"{start} {end}",
    },
    {
        "city": "Mikkeli",
        "name": "Mikkeli city",
        "query": lambda start, end:
            f"site:mikkeli.fi "
            f"Mikkeli tapahtumat kulttuuri "
            f"{start} {end}",
    },
    {
        "city": "Mikkeli",
        "name": "Mikaeli",
        "query": lambda start, end:
            f"site:mikaeli.fi "
            f"Mikkeli tapahtumat konsertti "
            f"{start} {end}",
    },
    {
        "city": "Pieksämäki",
        "name": "Pieksämäki city",
        "query": lambda start, end:
            f"site:pieksamaki.fi "
            f"Pieksämäki tapahtumat "
            f"{start} {end}",
    },
    {
        "city": "Pieksämäki",
        "name": "Poleeni",
        "query": lambda start, end:
            f"site:poleeni.fi "
            f"Pieksämäki tapahtumat konsertti teatteri näyttely "
            f"{start} {end}",
    },
    {
        "city": "Keuruu",
        "name": "Keuruu",
        "query": lambda start, end:
            f"site:keuruu.fi "
            f"Keuruu tapahtumat musiikki kulttuuri "
            f"{start} {end}",
    },
    {
        "city": "Heinola",
        "name": "Heinola",
        "query": lambda start, end:
            f"site:heinola.fi "
            f"Heinola tapahtumat kulttuuri musiikki "
            f"{start} {end}",
    },
    {
        "city": "Jämsä",
        "name": "Himos",
        "query": lambda start, end:
            f"site:himoslomat.fi "
            f"Himos tapahtumat keikat festivaalit "
            f"{start} {end}",
    },
]


VENUES = {
    "Jyväskylä": [
        "Tanssisali Lutakko",
        "Paviljonki",
        "Veturitallit",
        "Villa Rana",
        "Poppari",
        "RockNeck",
        "Musta Kynnys",
        "Revolution",
        "Club Escape",
        "Freetime",
        "London Jyväskylä",
        "Harry's Jyväskylä",
        "Hemingway’s Jyväskylä",
        "Lola Club Jyväskylä",
        "Parvi Jyväskylä",
        "Pub Aallonmurtaja",
        "Sohwi Jyväskylä",
        "Kulttuuritila Omenapuu",
        "Alakulttuuritalo Kramsu",
    ],
    "Lahti": [
        "Sibeliustalo",
        "Finlandia-klubi",
        "Möysän Musaklubi",
        "Ravintola Torvi",
        "VNUE Lahti",
        "Teatteri Vanha Juko",
        "Lahden kaupunginteatteri",
        "Malski",
        "Lahden Messukeskus",
    ],
    "Mikkeli": [
        "Mikaeli",
        "Kulttuuritalo Tempo",
        "Dom Mikkeli",
        "Olokorjaamo",
        "Gastropub Eino",
        "Wilhelm Public House",
        "Sport Pub Jälkipeli",
        "Bar & Bistro Route 431",
        "Mikkelin Teatteri",
    ],
    "Pieksämäki": [
        "Kulttuurikeskus Poleeni",
        "Pieksämäen Seurojentalo",
        "Pieksämäen Veturitallit",
    ],
    "Jämsä": [
        "Himos",
        "Himos Areena",
    ],
    "Keuruu": [
        "Keurusselkä Resort",
    ],
}


OUTDOOR_CITIES = [
    "Joutsa",
    "Jyväskylä",
    "Jämsä",
    "Mikkeli",
    "Lahti",
    "Heinola",
    "Pieksämäki",
    "Keuruu",
    "Hartola",
    "Sysmä",
    "Luhanka",
    "Toivakka",
    "Korpilahti",
    "Säynätsalo",
    "Pertunmaa",
    "Hirvensalmi",
    "Kangasniemi",
    "Mäntyharju",
]


def generate_search_queries(
    start_date: str,
    end_date: str,
) -> list[SearchQuery]:
    """Generate all discovery search queries for the configured period."""

    queries: list[SearchQuery] = []

    # General discovery — major cities
    for city in MAJOR_CITIES:
        for search in GENERAL_SEARCHES_MAJOR:
            queries.append(
                SearchQuery(
                    search_type="general",
                    category=search["type"],
                    location=city,
                    query=search["query"](city, start_date, end_date),
                )
            )

    # General discovery — smaller locations
    for city in LOCATIONS:
        if city in MAJOR_CITIES:
            continue

        for search in GENERAL_SEARCHES_SMALL:
            queries.append(
                SearchQuery(
                    search_type="general",
                    category=search["type"],
                    location=city,
                    query=search["query"](city, start_date, end_date),
                )
            )

    # Event aggregators
    for city in AGGREGATOR_CITIES:
        for source in AGGREGATORS:
            queries.append(
                SearchQuery(
                    search_type="event_source",
                    category="events",
                    location=city,
                    source=source["name"],
                    query=(
                        f"site:{source['domain']} "
                        f'"{city}" '
                        f"({source['keywords']}) "
                        f"{start_date} {end_date}"
                    ),
                )
            )

    # Stand-up / comedy
    for city in STANDUP_CITIES:
        for source in STANDUP_SOURCES:
            queries.append(
                SearchQuery(
                    search_type="stand_up_source",
                    category="stand_up",
                    location=city,
                    source=source["name"],
                    query=(
                        f"site:{source['domain']} "
                        f'"{city}" '
                        f"(stand-up OR standup OR comedy) "
                        f"{start_date} {end_date}"
                    ),
                )
            )

    # Official / local calendars
    for source in OFFICIAL_SOURCES:
        queries.append(
            SearchQuery(
                search_type="official_calendar",
                category="cultural",
                location=source["city"],
                source=source["name"],
                query=source["query"](start_date, end_date),
            )
        )

    # Venues
    for city, location_venues in VENUES.items():
        for venue in location_venues:
            queries.append(
                SearchQuery(
                    search_type="venue",
                    category="venue_events",
                    location=city,
                    venue=venue,
                    query=(
                        f'"{venue}" '
                        f'"{city}" '
                        f"(keikat OR konsertit OR tapahtumat OR "
                        f"live OR music OR stand-up OR comedy OR "
                        f"DJ OR club OR klubi) "
                        f"{start_date} {end_date}"
                    ),
                )
            )

    # Outdoor / public / community events
    for city in OUTDOOR_CITIES:
        queries.append(
            SearchQuery(
                search_type="outdoor",
                category="outdoor_events",
                location=city,
                query=(
                    f'"{city}" '
                    f"(puisto OR ulkoilma OR ulkoilmatapahtuma OR "
                    f"ulkoilmakonsertti OR tori OR markkinat OR messut OR "
                    f"festivaali OR festival OR yleisötapahtuma OR "
                    f"kylätapahtuma OR perhetapahtuma) "
                    f"{start_date} {end_date}"
                ),
            )
        )

    return queries