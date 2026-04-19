import meilisearch
from parse import stream_articles
from clean import clean_article

client = meilisearch.Client("http://localhost:7700", "parth123")
index = client.index("wikipedia")


def configure_index_settings():
    index.update_settings(
        {
            "searchableAttributes": ["title", "text"],
            "displayedAttributes": ["title", "excerpt", "url"],
            "rankingRules": [
                "words",
                "typo",
                "proximity",
                "attribute",
                "sort",
                "exactness",
            ],
        }
    )

def run_indexing(dump_path: str, batch_size: int = 1000):
    configure_index_settings()

    batch = []
    total = 0
    
    for article in stream_articles(dump_path):
        clean_text = clean_article(article["text"])
        batch.append({
            "id": total,
            "title": article["title"],
            "excerpt": clean_text[:500],      # for search result preview
            "text": clean_text,
            # "url": f"https://simple.wikipedia.org/wiki/{article['title'].replace(' ', '_')}"
            # "url": "http://www.mediawiki.org/xml/export-0.11/"
            "url": f"https://simple.wikipedia.org/wiki/{article['title'].replace(' ', '_')}"

        })
        total += 1
        
        if len(batch) >= batch_size:
            index.add_documents(batch)
            print(f"Indexed {total} articles...")
            batch = []
    
    if batch:
        index.add_documents(batch)
    
    print(f"Done. Total: {total} articles indexed.")

if __name__ == "__main__":
    run_indexing("simplewiki-latest-pages-articles.xml.bz2")


# import bz2
# import xml.etree.ElementTree as ET

# with bz2.open("simplewiki-latest-pages-articles.xml.bz2", "rb") as f:
#     for event, elem in ET.iterparse(f, events=["start"]):
#         print(elem.tag)  # print the first tag and stop
#         break