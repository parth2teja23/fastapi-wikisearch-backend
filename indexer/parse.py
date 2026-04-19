import bz2
import xml.etree.ElementTree as ET

def stream_articles(dump_path: str):
    namespace = "http://www.mediawiki.org/xml/export-0.11/"
    
    with bz2.open(dump_path, "rb") as f:
        for event, elem in ET.iterparse(f, events=["end"]):
            if elem.tag == f"{{{namespace}}}page":
                title = elem.findtext(f"{{{namespace}}}title")
                ns = elem.findtext(f"{{{namespace}}}ns")
                text = elem.findtext(
                    f".//{{{namespace}}}revision/{{{namespace}}}text"
                )
                
                if ns == "0" and text:  # ns=0 means actual articles
                    yield {"title": title, "text": text}
                
                elem.clear()  # free memory immediately