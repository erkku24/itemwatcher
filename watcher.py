import os
import re
import sqlite3
import smtplib
import ssl
import time

from email.message import EmailMessage
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup


# ============================================================
# ASETUKSET
# ============================================================

BASE_URL = "https://www.prisma.fi"

# Näitä seurataan.
POKEMON_BRAND_URL = (
    "https://www.prisma.fi/tuotemerkit/pokemon"
)

POKEMON_TCG_URL = (
    "https://www.prisma.fi/tuotemerkit/pokemon-tcg"
)

NEW_PRODUCTS_URL = (
    "https://www.prisma.fi/kategoriat/2047/uutuudet"
)

# Hakusanoja, jotka tekevät tuotteesta kiinnostavan.
KEYWORDS = [
    "pokemon",
    "pokémon",
    "pokemon tcg",
    "pokémon tcg",
    "pikachu",
    "charizard",
    "eevee",
    "bulbasaur",
    "charmander",
    "squirtle",
    "poké",
    "poke",
    "30th anniversary",
    "30-vuotis",
    "30 vuotta",
]

# Tiedosto, johon nähdyt tuotteet tallennetaan.
DATABASE = "products.sqlite3"

# Kuinka monta uutuussivua käydään läpi.
MAX_NEW_PRODUCT_PAGES = 10

# Pieni tauko pyyntöjen välillä.
REQUEST_DELAY = 0.5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": USER_AGENT,
        "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml",
    }
)


def download_page(url):
    print(f"Ladataan: {url}")

    response = session.get(
        url,
        timeout=30,
    )

    response.raise_for_status()

    time.sleep(REQUEST_DELAY)

    return response.text


# ============================================================
# TUOTELINKKIEN ETSIMINEN
# ============================================================

def extract_product_links(html):
    """
    Etsii Prisma.fi:n tuotesivuja HTML:stä.

    Tuotesivut näyttävät olevan muotoa:
        /tuotteet/123456789/...
    """

    soup = BeautifulSoup(html, "html.parser")

    products = {}

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        if "/tuotteet/" not in href:
            continue

        title = " ".join(link.stripped_strings).strip()

        if not title:
            continue

        url = urljoin(BASE_URL, href)

        # Poistetaan query-parametrit ja ankkurit.
        url = url.split("?")[0]
        url = url.split("#")[0]

        # Varmistetaan, että kyseessä näyttää olevan oikea tuotesivu.
        if not re.search(r"/tuotteet/\d+", url):
            continue

        products[url] = title

    return products


# ============================================================
# YHDEN TUOTESIVUN TEKSTI
# ============================================================

def get_product_text(url):
    """
    Lataa tuotteen sivun ja palauttaa siitä tekstin.
    """

    try:
        html = download_page(url)

    except Exception as error:
        print(
            f"Tuotesivun lataus epäonnistui: "
            f"{url} -> {error}"
        )

        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Poistetaan turhia elementtejä.
    for element in soup(
        ["script", "style", "noscript"]
    ):
        element.decompose()

    text = " ".join(
        soup.stripped_strings
    )

    return text


# ============================================================
# RELEVANSSIN TARKISTAMINEN
# ============================================================

def is_relevant(title, description=""):
    """
    Tarkistaa, liittyykö tuote Pokémoniin.

    Käytetään sekä tuotteen nimeä että tuotteen sivun tekstiä.
    """

    combined = (
        f"{title} {description}"
    ).casefold()

    for keyword in KEYWORDS:

        if keyword.casefold() in combined:
            return True

    return False


# ============================================================
# TIETOKANTA
# ============================================================

def initialize_database():

    connection = sqlite3.connect(
        DATABASE
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            first_seen TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP,
            relevant INTEGER DEFAULT 0
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    connection.commit()

    return connection


# ============================================================
# TUOTTEIDEN KERÄÄMINEN
# ============================================================

def crawl_page(url):
    """
    Hakee yhden sivun tuotteet.
    """

    try:
        html = download_page(url)

    except Exception as error:

        print(
            f"Sivun lataus epäonnistui: "
            f"{url}"
        )

        print(error)

        return {}

    return extract_product_links(html)


# ============================================================
# POKÉMON-BRÄNDI
# ============================================================

def crawl_pokemon_brand():

    print()
    print("=== POKÉMON-BRÄNDI ===")

    products = {}

    for page in range(
        1,
        MAX_NEW_PRODUCT_PAGES + 1
    ):

        if page == 1:

            url = POKEMON_BRAND_URL

        else:

            url = (
                f"{POKEMON_BRAND_URL}"
                f"?page={page}"
            )

        found = crawl_page(url)

        if not found:
            break

        products.update(found)

    return products


# ============================================================
# POKÉMON TCG
# ============================================================

def crawl_pokemon_tcg():

    print()
    print("=== POKÉMON TCG ===")

    products = {}

    for page in range(
        1,
        MAX_NEW_PRODUCT_PAGES + 1
    ):

        if page == 1:

            url = POKEMON_TCG_URL

        else:

            url = (
                f"{POKEMON_TCG_URL}"
                f"?page={page}"
            )

        found = crawl_page(url)

        if not found:
            break

        products.update(found)

    return products


# ============================================================
# UUTUUDET
# ============================================================

def crawl_new_products():

    print()
    print("=== UUTUUDET ===")

    products = {}

    for page in range(
        1,
        MAX_NEW_PRODUCT_PAGES + 1
    ):

        if page == 1:

            url = NEW_PRODUCTS_URL

        else:

            url = (
                f"{NEW_PRODUCTS_URL}"
                f"?page={page}"
            )

        found = crawl_page(url)

        if not found:
            break

        products.update(found)

    return products


# ============================================================
# KAIKKIEN LÄHTEIDEN YHDISTÄMINEN
# ============================================================

def collect_products():

    all_products = {}

    sources = [
        crawl_pokemon_brand(),
        crawl_pokemon_tcg(),
        crawl_new_products(),
    ]

    for source in sources:

        for url, title in source.items():

            all_products[url] = title

    return all_products


# ============================================================
# SÄHKÖPOSTI
# ============================================================

def send_email(products):

    smtp_host = os.environ[
        "SMTP_HOST"
    ]

    smtp_port = int(
        os.environ.get(
            "SMTP_PORT",
            "465"
        )
    )

    smtp_user = os.environ[
        "SMTP_USER"
    ]

    smtp_password = os.environ[
        "SMTP_PASSWORD"
    ]

    alert_to = os.environ[
        "ALERT_TO"
    ]

    message = EmailMessage()

    message["Subject"] = (
        "🔔 Prisma Pokémon - uusi tuote!"
    )

    message["From"] = smtp_user

    message["To"] = alert_to

    lines = []

    lines.append(
        "Prisma.fi:stä löytyi "
        "uusi Pokémoniin liittyvä tuote."
    )

    lines.append("")

    for product in products:

        title = product["title"]
        url = product["url"]

        lines.append(
            f"🎴 {title}"
        )

        lines.append(
            url
        )

        lines.append("")

    message.set_content(
        "\n".join(lines)
    )

    print()
    print(
        "Lähetetään sähköposti..."
    )

    if smtp_port == 465:

        context = (
            ssl.create_default_context()
        )

        with smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            context=context
        ) as smtp:

            smtp.login(
                smtp_user,
                smtp_password
            )

            smtp.send_message(
                message
            )

    else:

        with smtplib.SMTP(
            smtp_host,
            smtp_port
        ) as smtp:

            smtp.starttls(
                context=(
                    ssl.create_default_context()
                )
            )

            smtp.login(
                smtp_user,
                smtp_password
            )

            smtp.send_message(
                message
            )

    print(
        "Sähköposti lähetetty."
    )


# ============================================================
# PÄÄOHJELMA
# ============================================================

def main():

    print()
    print("=" * 60)
    print("PRISMA POKÉMON WATCHER")
    print("=" * 60)
    print()

    database = (
        initialize_database()
    )

    # --------------------------------------------------------
    # 1. Haetaan tuotteet useasta lähteestä
    # --------------------------------------------------------

    print(
        "Haetaan Prisma.fi:n tuotteita..."
    )

    products = collect_products()

    print()
    print(
        f"Kaikkiaan löydettiin "
        f"{len(products)} tuotetta."
    )

    # --------------------------------------------------------
    # 2. Haetaan aikaisemmin nähdyt tuotteet
    # --------------------------------------------------------

    existing = {}

    rows = database.execute(
        """
        SELECT url, title
        FROM products
        """
    ).fetchall()

    for url, title in rows:

        existing[url] = title

    print(
        f"Aikaisemmin tunnettuja tuotteita: "
        f"{len(existing)}"
    )

    # --------------------------------------------------------
    # 3. Etsitään uudet tuotteet
    # --------------------------------------------------------

    brand_new_products = []

    for url, title in products.items():

        if url not in existing:

            print()
            print(
                "UUSI TUOTE LÖYTYI:"
            )

            print(title)
            print(url)

            brand_new_products.append(
                {
                    "url": url,
                    "title": title,
                }
            )

    # --------------------------------------------------------
    # 4. Ensimmäinen ajo
    # --------------------------------------------------------

    initialized = database.execute(
        """
        SELECT value
        FROM settings
        WHERE key = 'initialized'
        """
    ).fetchone()

    first_run = (
        initialized is None
    )

    # --------------------------------------------------------
    # 5. Tutkitaan uudet tuotteet
    # --------------------------------------------------------

    relevant_new_products = []

    for product in brand_new_products:

        title = product["title"]
        url = product["url"]

        print()
        print(
            "Tutkitaan tuotetta:"
        )

        print(title)

        description = (
            get_product_text(url)
        )

        relevant = is_relevant(
            title,
            description
        )

        if relevant:

            print(
                "✓ Pokémon-tuote"
            )

            product["relevant"] = 1

            relevant_new_products.append(
                product
            )

        else:

            print(
                "✗ Ei tunnistettu "
                "Pokémon-tuotteeksi"
            )

            product["relevant"] = 0

        # Tallennetaan tuote.
        database.execute(
            """
            INSERT OR REPLACE INTO products
            (
                url,
                title,
                relevant
            )
            VALUES (?, ?, ?)
            """,
            (
                url,
                title,
                product["relevant"],
            )
        )

    # --------------------------------------------------------
    # 6. Päivitetään vanhojen tuotteiden last_seen
    # --------------------------------------------------------

    for url, title in products.items():

        if url in existing:

            database.execute(
                """
                UPDATE products
                SET
                    title = ?,
                    last_seen = CURRENT_TIMESTAMP
                WHERE url = ?
                """,
                (
                    title,
                    url,
                )
            )

    database.commit()

    # --------------------------------------------------------
    # 7. Ensimmäinen ajo = vain lähtötilan luonti
    # --------------------------------------------------------

    if first_run:

        print()
        print(
            "=" * 60
        )

        print(
            "ENSIMMÄINEN AJO"
        )

        print(
            "Nykyiset tuotteet tallennettiin "
            "lähtötilaksi."
        )

        print(
            "Sähköpostia ei lähetetä "
            "olemassa olevista tuotteista."
        )

        database.execute(
            """
            INSERT INTO settings(
                key,
                value
            )
            VALUES(
                'initialized',
                '1'
            )
            """
        )

        database.commit()

        database.close()

        return

    # --------------------------------------------------------
    # 8. Lähetetään ilmoitus
    # --------------------------------------------------------

    if relevant_new_products:

        print()
        print(
            "=" * 60
        )

        print(
            f"LÖYTYI "
            f"{len(relevant_new_products)} "
            f"UUTTA RELEVANTTIA TUOTETTA!"
        )

        print(
            "=" * 60
        )

        send_email(
            relevant_new_products
        )

    else:

        print()
        print(
            "Uusia relevantteja "
            "Pokémon-tuotteita ei löytynyt."
        )

    database.close()

    print()
    print("Valmis.")


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
