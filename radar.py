# Radar de chollos y errores de precio -> Telegram
# Solo usa Python estándar (no hay que instalar nada).

import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

# ============ CONFIGURACIÓN (puedes editar esto) ============

# Feeds a vigilar. "solo_errores" = todo lo que salga ahí es candidato.
# Si una fuente tiene varias direcciones, se usa la primera que funcione.
FEEDS = [
    {"urls": [
        "https://www.chollometro.com/rss/grupo/errores-precio",
        "https://www.chollometro.com/rss/grupo/error-de-precio",
        "https://www.chollometro.com/rss/grupos/errores-de-precio",
        "https://www.chollometro.com/rss/errores-de-precio",
    ], "solo_errores": True, "opcional": True},
    {"urls": ["https://www.chollometro.com/rss/nuevos"], "solo_errores": False},
    {"urls": ["https://www.chollometro.com/rss/hot"], "solo_errores": False, "opcional": True},
]

# Palabras que delatan un posible error de precio
PALABRAS_ERROR = [
    "error de precio", "error en el precio", "error precio", "fallo de precio",
    "bug de precio", "precio erróneo", "precio erroneo", "error?", "¿error",
]

# Solo nos interesan estos temas (para el feed general)
PALABRAS_TEMA = [
    "thermomix", "robot de cocina", "monsieur cuisine", "mambo", "dyson", "airwrap",
    "roborock", "roomba", "conga", "dreame", "ecovacs", "robot aspirador", "aspiradora",
    "freidora", "ninja", "cosori", "cafetera", "nespresso", "delonghi", "de'longhi",
    "krups", "philips", "iphone", "ipad", "macbook", "airpods", "apple watch", "samsung",
    "galaxy", "xiaomi", "pixel", "switch", "nintendo", "playstation", "ps5", "xbox",
    "kindle", "portátil", "portatil", "monitor", "tablet", "auriculares", "sony",
    "bose", "jbl", "televisor", "smart tv", "oled", "lego", "garmin", "gopro", "dji",
]

# Descuento mínimo (si en el texto aparecen precio actual y anterior). 0.5 = 50%
DESCUENTO_MINIMO = 0.5

# Ignorar chollos por debajo de este precio (euros)
PRECIO_MINIMO = 25

# Palabras que descartan el chollo
PALABRAS_EXCLUIR = ["reacondicionado", "funda", "protector", "cable", "carcasa", "cupón descuento"]

# ============================================================

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MODO = os.environ.get("MODO", "normal").strip().lower()
MEMORIA = "seen.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

RE_PRECIO = re.compile(r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s?€")


def a_numero(txt):
    txt = txt.replace(" ", "")
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", txt):
        txt = txt.replace(".", "")
    try:
        return float(txt)
    except ValueError:
        return None


def descargar(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, */*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def leer_feed(url):
    raiz = ET.fromstring(descargar(url))
    items = []
    for it in raiz.iter("item"):
        d = {"titulo": "", "link": "", "id": "", "texto": "", "tienda": "", "precio": None}
        for hijo in it:
            tag = hijo.tag.split("}")[-1].lower()
            if tag == "title":
                d["titulo"] = (hijo.text or "").strip()
            elif tag == "link":
                d["link"] = (hijo.text or "").strip()
            elif tag == "guid":
                d["id"] = (hijo.text or "").strip()
            elif tag == "description":
                d["texto"] = re.sub("<[^>]+>", " ", html.unescape(hijo.text or ""))
            elif tag == "merchant":
                d["tienda"] = hijo.attrib.get("name", "")
                if hijo.attrib.get("price"):
                    m = RE_PRECIO.search(hijo.attrib["price"] + "€")
                    d["precio"] = a_numero(m.group(1)) if m else None
        d["id"] = d["id"] or d["link"] or d["titulo"]
        items.append(d)
    return items


def analizar(item, solo_errores):
    """Devuelve (es_candidato, motivo, descuento)."""
    texto = (item["titulo"] + " " + item["texto"]).lower()
    precios = [p for p in (a_numero(x) for x in RE_PRECIO.findall(item["titulo"] + " " + item["texto"])) if p]
    actual = item["precio"] or (min(precios) if precios else None)
    descuento = None
    if precios and actual and max(precios) > actual:
        descuento = 1 - actual / max(precios)

    if any(p in texto for p in PALABRAS_EXCLUIR):
        return False, "", descuento
    if actual is not None and actual < PRECIO_MINIMO:
        return False, "", descuento
    if solo_errores:
        return True, "Categoría errores de precio", descuento
    if not any(p in texto for p in PALABRAS_TEMA):
        return False, "", descuento
    if any(p in texto for p in PALABRAS_ERROR):
        return True, "Mencionan posible error de precio", descuento
    if descuento and descuento >= DESCUENTO_MINIMO:
        return True, f"Bajada del {descuento:.0%}", descuento
    return False, "", descuento


def telegram(texto):
    if not TOKEN or not CHAT_ID:
        print("[sin Telegram configurado]\n" + texto)
        return
    datos = json.dumps({"chat_id": CHAT_ID, "text": texto, "parse_mode": "HTML",
                        "disable_web_page_preview": False}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=datos,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()


def formatear(item, motivo, descuento):
    e = html.escape
    lineas = [f"🚨 <b>{e(item['titulo'])}</b>"]
    if item["tienda"]:
        lineas.append(f"🏪 {e(item['tienda'])}")
    if item["precio"]:
        lineas.append(f"💶 {item['precio']:.2f} €")
    if descuento:
        lineas.append(f"📉 -{descuento:.0%}")
    lineas.append(f"🔎 {e(motivo)}")
    lineas.append(e(item["link"]))
    return "\n".join(lineas)


def main():
    try:
        with open(MEMORIA) as f:
            vistos = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        vistos = []
    primera_vez = not vistos
    vistos_set = set(vistos)

    informe, avisos, nuevos_ids = [], [], []
    for feed in FEEDS:
        items, errores = None, []
        for url in feed["urls"]:
            try:
                items = leer_feed(url)
                informe.append(f"✅ {url} → {len(items)} chollos")
                break
            except Exception as ex:
                errores.append(f"{url} → {type(ex).__name__}: {ex}")
        if items is None:
            if feed.get("opcional"):
                informe.append(f"⚪ Fuente opcional no disponible ({len(errores)} direcciones probadas)")
            else:
                informe.append("❌ " + " | ".join(errores))
            continue
        for it in items:
            if it["id"] in vistos_set:
                continue
            vistos_set.add(it["id"])
            nuevos_ids.append(it["id"])
            ok, motivo, desc = analizar(it, feed["solo_errores"])
            if ok:
                avisos.append(formatear(it, motivo, desc))

    print("\n".join(informe))

    if MODO == "prueba":
        msg = "✅ <b>Radar funcionando</b>\n\n" + html.escape("\n".join(informe))
        if avisos:
            msg += f"\n\nAhora mismo cumplen los filtros {len(avisos)}. Ejemplo:\n\n" + avisos[0]
        telegram(msg)
    elif primera_vez:
        telegram("🟢 Radar activado. A partir de ahora te aviso de lo nuevo que cumpla los filtros.")
    else:
        for a in avisos[:15]:
            telegram(a)

    if MODO != "prueba":
        vistos = (vistos + nuevos_ids)[-3000:]
        with open(MEMORIA, "w") as f:
            json.dump(vistos, f)

    if not any(l.startswith("✅") for l in informe):
        sys.exit(1)


if __name__ == "__main__":
    main()
