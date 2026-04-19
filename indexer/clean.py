import mwparserfromhell

def clean_article(raw_text: str) -> str:
    parsed = mwparserfromhell.parse(raw_text)
    clean = parsed.strip_code()          # removes all {{templates}}, [[links]] etc
    clean = clean.strip()
    return clean[:5000]                  # store first 5000 chars per article