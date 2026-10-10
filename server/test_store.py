import trafilatura
from extract import extract_page
from store import add_page, search, clear

clear()
for url in ["https://demo-site-1...", "https://demo-site-2..."]:
    html = trafilatura.fetch_url(url)
    _, meta, passages = extract_page(html, url=url)
    print(meta["title"], "->", add_page(meta, passages), "passages")

for sentence in [
    "A sentence that paraphrases something from site 1.",
    "A sentence unrelated to either article.",
]:
    print("\n", sentence)
    for r in search(sentence):
        print(f"  {r['score']:.2f}  {r['source']['title']}: {r['text'][:80]}...")