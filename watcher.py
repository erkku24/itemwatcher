import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright


BASE_URL = "https://www.prisma.fi"
POKEMON_BRAND_URL = "https://www.prisma.fi/tuotemerkit/pokemon"

SEARCH_TERM = "pokemon"

KNOWN_PRODUCTS_FILE = Path("known_products.json")

# Turvaraja sivutukselle.
MAX_PAGES = 20


def normalize_product_url(url):
    """
    Muuttaa tuotteen URL:n yhtenäiseen muotoon.
    Query-parametrit ja #fragmentit poistetaan.
    """

    absolute = urljoin(BASE_URL, url)

    parts = urlsplit(absolute)

    clean = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path.rstrip("/"),
            "",
            "",
        )
    )

    return clean


def extract_products(page):
    """
    Kerää sivulla näkyvien Prisma-tuotteiden URL:t ja nimet.
    """

    products = {}

    links = page.locator('a[href*="/tuotteet/"]')

    count = links.count()

    for i in range(count):

        link = links.nth(i)

        try:
            href = link.get_attribute("href")

            if not href:
                continue

            url = normalize_product_url(href)

            # Varmistetaan, että kyseessä on tuotesivu.
            if "/tuotteet/" not in url:
                continue

            title = link.inner_text().strip()

            # Jos linkin tekstissä ei ole nimeä,
            # yritetään käyttää aria-labelia.
            if not title:
                title = link.get_attribute("aria-label") or ""

            title = " ".join(title.split())

            # Jos sama URL löytyy monta kertaa,
            # säilytetään paras nimi.
            if url not in products or len(title) > len(products[url]):
                products[url] = title

        except Exception as error:
            print(f"Linkin lukeminen epäonnistui: {error}")

    return products


def scroll_page(page):
    """
    Vierittää sivua alaspäin, jotta mahdollisesti
    dynaamisesti latautuvat tuotteet tulevat näkyviin.
    """

    previous_height = 0

    for _ in range(15):

        height = page.evaluate("document.body.scrollHeight")

        if height == previous_height:
            break

        previous_height = height

        page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )

        page.wait_for_timeout(700)


def collect_current_page(page):
    """
    Vierittää sivun ja kerää tuotteet.
    """

    scroll_page(page)

    return extract_products(page)


def find_next_page(page):
    """
    Yrittää löytää sivutuksen Seuraava-painikkeen.
    """

    selectors = [
        'a[rel="next"]',
        'a[aria-label*="Seuraava"]',
        'a[aria-label*="seuraava"]',
    ]

    for selector in selectors:

        locator = page.locator(selector)

        if locator.count() > 0:

            try:
                href = locator.first.get_attribute("href")

                if href:
                    return urljoin(BASE_URL, href)

            except Exception:
                pass

    # Varavaihtoehto: etsitään linkin tekstistä.

    links = page.locator("a")

    for i in range(links.count()):

        link = links.nth(i)

        try:
            text = link.inner_text().strip().lower()
            href = link.get_attribute("href")

            if href and (
                text == "seuraava"
                or text == "seuraava sivu"
            ):
                return urljoin(BASE_URL, href)

        except Exception:
            pass

    return None


def collect_paginated_products(page):
    """
    Kerää kaikki tuotteet nykyiseltä sivulta
    ja mahdollisilta seuraavilta sivuilta.
    """

    all_products = {}
    visited_pages = set()

    for page_number in range(1, MAX_PAGES + 1):

        current_url = page.url

        if current_url in visited_pages:
            break

        visited_pages.add(current_url)

        print(f"Luetaan sivu {page_number}: {current_url}")

        products = collect_current_page(page)

        print(
            f"  Tuotteita tällä sivulla: {len(products)}"
        )

        all_products.update(products)

        next_url = find_next_page(page)

        if not next_url:
            break

        if next_url in visited_pages:
            break

        page.goto(
            next_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(1000)

    return all_products


def collect_brand_products(page):
    """
    Kerää Pokémon-brändisivun tuotteet.
    """

    print("\n=== POKÉMON-BRÄNDISIVU ===")

    page.goto(
        POKEMON_BRAND_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(1500)

    products = collect_paginated_products(page)

    print(
        f"Pokémon-brändisivulta löytyi "
        f"{len(products)} yksilöllistä tuotetta."
    )

    return products


def collect_search_products(page):
    """
    Tekee Prisma.fi:n hakukentässä haun sanalla pokemon
    ja kerää hakutulosten tuotteet.
    """

    print('\n=== PRISMA-HAKU: "pokemon" ===')

    page.goto(
        BASE_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(1000)

    # Etsitään hakukenttä useammalla tavalla,
    # jotta pieni muutos sivustossa ei heti riko skriptiä.

    selectors = [
        'input[type="search"]',
        'input[placeholder*="Hae"]',
        'input[aria-label*="Hae"]',
        'input[placeholder*="hae"]',
    ]

    search_box = None

    for selector in selectors:

        locator = page.locator(selector)

        if locator.count() > 0:
            search_box = locator.first
            break

    if search_box is None:
        raise RuntimeError(
            "Prisman hakukenttää ei löytynyt."
        )

    search_box.fill(SEARCH_TERM)
    search_box.press("Enter")

    page.wait_for_load_state(
        "domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(2000)

    print(f"Hakutulossivu: {page.url}")

    products = collect_paginated_products(page)

    print(
        f'Haulla "{SEARCH_TERM}" löytyi '
        f"{len(products)} yksilöllistä tuotetta."
    )

    return products


def load_known_products():
    """
    Lukee edellisillä ajoilla nähdyt tuotteet.
    """

    if not KNOWN_PRODUCTS_FILE.exists():
        return None

    try:

        with KNOWN_PRODUCTS_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            return {}

        return data

    except Exception as error:

        print(
            f"Vanhojen tuotteiden lukeminen "
            f"epäonnistui: {error}"
        )

        return {}


def save_known_products(products):
    """
    Tallentaa KAIKKI koskaan nähdyt tuotteet.

    Tuotetta ei poisteta historiasta, vaikka se
    katoaisi myöhemmin Prismasta.
    """

    with KNOWN_PRODUCTS_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            products,
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


def send_email(new_products):
    """
    Lähettää sähköpostin uusista URL:eista.
    """

    if not new_products:
        return

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ["SMTP_PORT"])
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    alert_to = os.environ["ALERT_TO"]

    message = EmailMessage()

    if len(new_products) == 1:
        subject = "Uusi Pokémon-tuote Prisma.fi:ssä"
    else:
        subject = (
            f"{len(new_products)} uutta "
            f"Pokémon-tuotetta Prisma.fi:ssä"
        )

    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = alert_to

    lines = [
        "Prisman Pokémon-seuranta löysi uusia tuotteita.",
        "",
    ]

    for url, title in sorted(
        new_products.items(),
        key=lambda item: item[1].lower(),
    ):

        name = title or "Nimi ei löytynyt"

        lines.append(name)
        lines.append(url)
        lines.append("")

    message.set_content("\n".join(lines))

    with smtplib.SMTP_SSL(
        smtp_host,
        smtp_port,
        timeout=30,
    ) as server:

        server.login(
            smtp_user,
            smtp_password,
        )

        server.send_message(message)

    print(
        f"Sähköposti lähetetty. "
        f"Uusia tuotteita: {len(new_products)}"
    )


def main():

    print("Prisma Pokémon watcher käynnistyy.")

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            locale="fi-FI",
            viewport={
                "width": 1440,
                "height": 1000,
            },
        )

        try:

            # 1. Pokemon-haku

            search_products = collect_search_products(page)

            # 2. Pokemon-brändisivu

            brand_products = collect_brand_products(page)

        finally:

            browser.close()

    # Yhdistetään lähteet URL:n perusteella.

    current_products = {}

    current_products.update(search_products)
    current_products.update(brand_products)

    print("\n=== YHTEENVETO ===")

    print(
        f'Pokemon-haun tuotteita: '
        f"{len(search_products)}"
    )

    print(
        f"Pokémon-brändisivun tuotteita: "
        f"{len(brand_products)}"
    )

    print(
        f"Yksilöllisiä URL:eja yhteensä: "
        f"{len(current_products)}"
    )

    # Turvatarkistus.
    #
    # Jos sivusto ei latautunut oikein ja saamme vain
    # muutaman tuotteen, emme halua tallentaa rikkinäistä
    # tulosta normaaliksi tilanteeksi.

    if len(current_products) < 20:

        raise RuntimeError(
            "Tuotteita löytyi epäilyttävän vähän "
            f"({len(current_products)}). "
            "Tallennusta ei tehdä."
        )

    known_products = load_known_products()

    # Ensimmäinen onnistunut ajo muodostaa lähtötilanteen.
    # Sähköpostia ei lähetetä kaikista nykyisistä tuotteista.

    if known_products is None:

        print(
            "\nEnsimmäinen ajo."
            "\nTallennetaan nykyiset tuotteet lähtötilanteeksi."
        )

        save_known_products(current_products)

        print(
            f"Tallennettu {len(current_products)} tuotetta."
        )

        return

    # Verrataan URL:eja, EI tuotemäärää.

    new_products = {
        url: title
        for url, title in current_products.items()
        if url not in known_products
    }

    if new_products:

        print(
            f"\nUUSIA URL:EJA: {len(new_products)}"
        )

        for url, title in new_products.items():

            print(f"\n{title}")
            print(url)

        # Lähetetään ilmoitus ennen historian tallentamista.
        # Jos sähköposti epäonnistuu, ajo epäonnistuu eikä
        # uusia tuotteita merkitä nähdyiksi.

        send_email(new_products)

    else:

        print("\nEi uusia tuote-URL:eja.")

    # Säilytetään myös tuotteet, jotka ovat poistuneet
    # nykyisestä valikoimasta. Näin vanhan tuotteen paluu
    # ei aiheuta turhaa "uusi tuote" -ilmoitusta.

    known_products.update(current_products)

    save_known_products(known_products)

    print(
        f"\nHistoriassa nyt "
        f"{len(known_products)} tuotetta."
    )


if __name__ == "__main__":
    send_email({
        "https://www.prisma.fi/": "TESTI – Prisma Pokémon watcher"
    })
