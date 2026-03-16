"""
signal_parser.py
================
Pure-Python signal parsing logic extracted from Telegram Signal Copier (TSC 5.4.4).

Changes from previous version
------------------------------
* ``filename`` key removed from every result dict.
* Every result dict now carries structured JSON-ready fields that match the
  signal history format observed in the desktop app, e.g.:
      /open USDJPY,SELL,1.54,0,1111,3333,4444,6666,-1,4,3810826194,copier
      /close USDJPY,5,TP1
* ``route_signal()`` returns a list of dicts with keys:
      kind        – command kind (open | close | update | …)
      command     – the raw command string (/open …, /close …, etc.)
      symbol      – trading pair
      direction   – BUY | SELL | "" (empty for non-open kinds)
      entry_price – entry price string ("" = market order)
      sl          – stop-loss value string
      tps         – list of TP value strings   ← replaces flat tp1…tp5
      msg_id      – Telegram message ID
      channel_id  – channel numeric ID
      channel     – channel display name (8-char truncated)
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# Default symbol lists
# ---------------------------------------------------------------------------

DEF_FXLIST = [
    "USDCHF","GBPUSD","EURUSD","USDJPY","USDCAD","AUDUSD","EURGBP","EURAUD","EURCHF","EURJPY",
    "GBPCHF","CADJPY","GBPJPY","AUDNZD","AUDCAD","AUDCHF","AUDJPY","CHFJPY","EURNZD","EURCAD",
    "CADCHF","NZDJPY","NZDUSD","XAUUSD","GBPCAD","EURCZK","EURDKK","EURHKD","EURMXN","EURNOK",
    "EURPLN","EURSEK","EURTRY","EURZAR","GBPDKK","GBPNOK","GBPSEK","NOKSEK","USDCNH","USDCZK",
    "USDDKK","USDHKD","USDHUF","USDILS","USDMXN","USDNOK","USDPLN","USDRUB","USDSEK","USDSGD",
    "USDTRY","USDZAR","AUS200","ESP35","EUSTX50","FRA40","GER30","JPN225","NAS100","SPX500",
    "UK100","US30","DOLLAR","AAPL","ABNB","ADSGn","AIRF.PA","ALVG","AMZN","BAYGn","BMWG",
    "BNPP.PA","CBKG","CSCO","DAIGn","DANO.PA","DASH","DBKGn","DPWGn","EBAY","EONGn","GOOG",
    "IBE.MC","ILMN","INTC","LHAG","LVMH.PA","MAP.MC","MRNA","MSFT","MTCH","NFLX","ORCL",
    "PLTR","QCOM","RACE","SAN.MC","SIEGn","SOGN.PA","TEF.MC","TEVA","TGT","TOTF.PA","TSLA",
    "TWTR","VOWG_p","WMT","XOM","GBPAUD","GBPNZD","NZDCAD","NZDCHF","UKOIL","USOIL","XAGUSD",
    "XAUEUR","XPTUSD","ADAUSD","BITUSD","BTCUSD","DASHBTC","DASHUSD","DOGEUSD","DOTUSD",
    "EOSBIT","EOSUSD","ETCUSD","ETHBTC","ETHUSD","IOTABIT","IOTAUSD","LTCBTC","LTCUSD",
    "LUNAUSD","NEOBTC","NEOUSD","OMGBIT","OMGUSD","QTUMBIT","SOLUSD","TRXUSD","USDTUSD",
    "XMRBTC","XMRUSD","XRPBIT","XRPUSD","XTZUSD","ZECBTC","GOLD",
]

FXSMALL = [
    "USD","CHF","GBP","EUR","JPY","CAD","AUD","NZD","SEK","NOK","CNH","CZK","DKK","HKD","HUF",
    "MXN","PLN","XAU","TRY","ZAR","US","OIL","XAG","XPT","ADA","BIT","BTC","DASH","DOGE","DOT",
    "EOS","ETC","ETH","IOTA","LTC","LUNA","NEO","OMG","QTUM","SOL","TRX","USDT","XMR","XRP",
    "XTZ","ZEC",
]


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    try:
        from unidecode import unidecode
        return unidecode(text)
    except ImportError:
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))


def _clean_text(text: str) -> str:
    return text.replace("/", "").replace("#", "").replace("-", "").replace('"', "")


# ---------------------------------------------------------------------------
# Symbol matching
# ---------------------------------------------------------------------------

def find_matching_pair(
    message: str,
    items_list: list[str],
    affixes: set[str] | None = None,
) -> str | None:
    for item in items_list:
        if re.search(r"\b" + re.escape(item) + r"\b", message):
            return item
        if affixes:
            aff_group = "(?:" + "|".join(map(re.escape, affixes)) + ")*"
            pattern = r"\b" + aff_group + re.escape(item) + aff_group + r"\b"
            if re.search(pattern, message):
                return item
    return None


def concat_codes(words: list[str], codes: list[str]) -> str:
    found = [w for w in words if w in codes]
    return "".join(found[:2]) if len(found) >= 2 else "no_pair"


def _resolve_symbol(
    text: str,
    fxlist: list[str] | None = None,
    affixes: set[str] | None = None,
) -> str:
    if fxlist is None:
        fxlist = DEF_FXLIST
    modtext = _clean_text(text)
    match = find_matching_pair(modtext, fxlist, affixes)
    if match and len(match) > 1:
        return match
    return concat_codes(modtext.split(), FXSMALL)


# ---------------------------------------------------------------------------
# Entry-price extraction
# ---------------------------------------------------------------------------

def extract_entry_price(
    text: str,
    array: list[str] | None = None,
    s: str | None = None,
    direction: str | None = None,
    fxlist: list[str] | None = None,
    affixes: set[str] | None = None,
) -> str:
    if array is None:
        array = [line.strip() for line in text.split("\n") if line.strip()]
    if s is None:
        s = _resolve_symbol(text, fxlist, affixes)
    if direction is None:
        direction = "BUY" if "BUY" in text else ("SELL" if "SELL" in text else "")

    price = ""

    if "ENPRICE" in text:
        for idx, line in enumerate(array):
            working = line.replace(s, "") if s in line else line
            if "ENPRICE" in working and len(price) < 4:
                working = working.replace(" ", "")
                m = re.search(r"ENPRICE.*?(\d+\.?\d*(?:[-/_]\d+\.?\d*)?)", working)
                price = m.group(1) if m else "0"
                if price in ("", "0", "0.0") and idx + 1 < len(array):
                    nxt = array[idx + 1].strip()
                    if nxt[:1].isdigit():
                        price = "".join(c for c in nxt if c.isdigit() or c in "./-_")
                return price

    elif "BUY" in text or "SELL" in text:
        for idx, line in enumerate(array):
            working = line.replace(s, "") if s in line else line
            if ("BUY" in working or "SELL" in working) and len(price) < 4:
                working = working.replace(" ", "")
                m = re.search(
                    rf"{re.escape(direction)}.*?(\d+\.?\d*(?:[-/_]\d+\.?\d*)?)",
                    working,
                )
                price = m.group(1) if m else "0"
                if price in ("", "0", "0.0") and idx + 1 < len(array):
                    nxt = array[idx + 1].strip()
                    if nxt[:1].isdigit():
                        price = "".join(c for c in nxt if c.isdigit() or c in "./-_")
                return price

    return price


# ---------------------------------------------------------------------------
# TP pre-processing helpers
# ---------------------------------------------------------------------------

def _split_tp_lines(array: list[str]) -> list[str]:
    new_array: list[str] = []
    for line in array:
        if "TP" in line and not re.search(r"(^|\n)\s*TP", line):
            parts = re.split(r"(?<![a-zA-Z])TP(?![a-zA-Z])", line)
            parts = [p.strip() for p in parts if p.strip()]
            for i, part in enumerate(parts):
                new_array.append(part if i == 0 else f"TP {part}")
        else:
            new_array.append(line)
    return new_array


def _expand_tp_ranges(array: list[str]) -> list[str]:
    """
    When a single TP line contains multiple price values separated by
    punctuation (e.g. ``TP 2345 / 2360 / 2380``) keep only the first price
    in-place and append the remainder as new ``TP <value>`` lines.

    Lines of the form ``TP1 1111`` (ordinal label + single price) are left
    untouched — the ``1`` is a label, not a price to be split.
    """
    result = list(array)
    for line in list(result):
        if "TP" not in line:
            continue

        # Require at least two separator-delimited values after the TP token.
        m = re.search(
            r"TP\d*\s*[:\s=]?\s*(\d+\.?\d*|OPEN)"
            r"(\s*[-:,/|]\s*(\d+\.?\d*|OPEN)\s*)+",
            line,
        )
        if not m:
            continue  # single value or no price — nothing to expand

        all_tokens = re.findall(r"(\d+\.?\d*|OPEN)", m.group(0))

        # If the first token is a short integer (≤ 2 digits) it is the
        # ordinal label (TP1, TP2 …).  Price values start from index 1.
        start = 0
        if (
            len(all_tokens) >= 2
            and all_tokens[0].isdigit()
            and len(all_tokens[0]) <= 2
        ):
            start = 1

        prices = all_tokens[start:]
        if len(prices) <= 1:
            continue  # only one real price after stripping label

        first    = prices[0]
        modified = re.sub(
            r"TP\d*\s*[:\s=]?\s*(\d+\.?\d*|OPEN)"
            r"(\s*[-:,/|]\s*(\d+\.?\d*|OPEN)\s*)+",
            f"TP {first} ",
            line,
        )
        result[result.index(line)] = modified
        for extra in prices[1:]:
            result.append(f"TP {extra}")

    return result


def _extract_sl_and_tps(array: list[str]) -> tuple[str, list[str]]:
    """
    Extract SL and all TP values from a pre-processed line array.

    SL patterns handled
    -------------------
    - ``SL 5000``  / ``SL: 5000``  / ``SL5000``
    - ``STOP LOSS 5000``  / ``STOPLOSS 5000``  (common signal-provider aliases)

    TP patterns handled
    -------------------
    - ``TP 6000``        – plain TP with price
    - ``TP1 6000``       – ordinal label attached (no space)
    - ``TP1: 6000``      – ordinal label with colon separator
    - ``TP 1 6000``      – ordinal label separated by a space  ← key new case
    - ``TP 6000.0``      – decimal prices

    A token is treated as an ordinal label (not a price) when it is a short
    integer of ≤ 2 digits immediately after ``TP``.

    Returns
    -------
    (sl, [tp1_val, tp2_val, ...])  – raw strings; list may be empty.
    """
    sl = "0"
    tps: list[str] = []

    for line in array:

        # ── SL extraction ────────────────────────────────────────────────────
        # Try "SL" keyword first (strict word boundary)
        if "SL" in line:
            m = re.search(r"(?<!\w)SL\s*[:\s=]?\s*(\d+\.?\d*)", line)
            if m:
                sl = m.group(1)

        # Fallback: "STOP LOSS" / "STOPLOSS" written out in full
        if sl == "0" and ("STOP" in line):
            m = re.search(r"STOP\s*LOSS\s*[:\s=]?\s*(\d+\.?\d*)", line)
            if m:
                sl = m.group(1)

        # ── TP extraction ────────────────────────────────────────────────────
        if "TP" in line:
            # Unified pattern:
            #   TP          – literal keyword (word boundary)
            #   \d*         – optional ordinal digit(s) glued to TP  (e.g. TP1)
            #   (?:\s+\d+)? – optional space-separated ordinal digit (e.g. TP 1)
            #   \s*[:\s=]?  – optional separator
            #   \s*         – any whitespace
            #   (\d+\.?\d*) – the actual price value  (captured)
            #
            # We use a two-step approach:
            # 1. Find the candidate region after each TP token.
            # 2. Skip an ordinal label (≤ 2 digits) if it appears before the price.

            for m in re.finditer(r"(?<!\w)TP(\d*)\s*[:\s=]?\s*(\d+\.?\d*)", line):
                label_part = m.group(1)   # digits glued to TP, e.g. "1" from "TP1"
                first_num  = m.group(2)   # first number captured after TP+label

                # If label_part is empty and first_num is a short ordinal (≤ 2 digits),
                # it's "TP 1 6000" — skip first_num and grab the next number on the line
                # at the same position.
                if not label_part and first_num.isdigit() and len(first_num) <= 2:
                    # Look for the actual price right after this ordinal
                    rest = line[m.end():]
                    pm = re.search(r"^\s*(\d+\.?\d*)", rest)
                    if pm:
                        tps.append(pm.group(1))
                    # else: orphaned ordinal with no price — skip
                else:
                    # first_num is the real price (or label_part was the ordinal)
                    tps.append(first_num)

    return sl, tps


def _apply_pips(
    sl: str,
    tps: list[str],
    sl_in_pips: bool,
    tp_in_pips: bool,
) -> tuple[str, list[str]]:
    """Append ' pips' suffix to SL and/or TP values when flags are set."""
    if sl_in_pips and sl != "0":
        sl = sl + " pips"
    if tp_in_pips:
        tps = [(v + " pips") if v not in ("0", "-1") else v for v in tps]
    return sl, tps


# ---------------------------------------------------------------------------
# Result dict builder
# ---------------------------------------------------------------------------

def _make_result(
    kind: str,
    command: str,
    symbol: str = "",
    direction: str = "",
    entry_price: str = "",
    sl: str = "0",
    tps: list[str] | None = None,
    msg_id: str = "",
    channel_id: str = "",
    channel: str = "",
    close_tp: str = "",          # e.g. "TP1" for partial close
    new_sl: str = "",            # for update/edit kinds
    new_tps: list[str] | None = None,  # for update/edit kinds
) -> dict:
    """
    Central factory for every result dict.

    All keys are always present so callers can rely on the schema without
    guard clauses. Unused keys carry their zero-value ("" or []).
    """
    return {
        "kind":        kind,
        "command":     command,
        "symbol":      symbol,
        "direction":   direction,
        "entry_price": entry_price,
        "sl":          sl,
        "tps":         tps if tps is not None else [],
        "msg_id":      msg_id,
        "channel_id":  channel_id,
        "channel":     channel,
        # extra context fields (non-empty only when relevant)
        "close_tp":    close_tp,
        "new_sl":      new_sl,
        "new_tps":     new_tps if new_tps is not None else [],
    }


# ---------------------------------------------------------------------------
# channel_open
# ---------------------------------------------------------------------------

def channel_open(
    text: str,
    msg_id: str,
    channel_id: str,
    price_rng: int,
    sl_in_pips: bool,
    tp_in_pips: bool,
    channel: str = "no name",
    fxlist: list[str] | None = None,
    affixes: set[str] | None = None,
    entry_override: str | None = None,
) -> dict:
    """
    Parse a fresh open-trade signal.

    Returns a result dict (see ``_make_result``).
    The ``command`` field reproduces the desktop-app format exactly:
        /open SYMBOL,DIR,PRICE,SL,TP1,TP2,...,MSG_ID,CHANNEL_ID,CHANNEL
    """
    if fxlist is None:
        fxlist = DEF_FXLIST

    array = [line.strip() for line in text.split("\n") if line.strip()]
    symbol    = _resolve_symbol(text, fxlist, affixes)
    direction = "BUY" if "BUY" in text else ("SELL" if "SELL" in text else "")

    # ── entry price ──────────────────────────────────────────────────────────
    if entry_override is not None and str(entry_override).strip():
        price = str(entry_override).strip()
    else:
        price = extract_entry_price(text, array, symbol, direction, fxlist, affixes)
        if not price or price == "0":
            price = "0"
        elif price_rng != 3:
            try:
                parts = re.split(r"[-/_]", price)
                if price_rng == 2 and len(parts) > 1:
                    price = str((float(parts[0]) + float(parts[1])) / 2)
                else:
                    price = str(float(parts[price_rng]) if len(parts) > 1 else float(parts[0]))
            except Exception:
                price = "0"

    # ── TP processing ────────────────────────────────────────────────────────
    array = _split_tp_lines(array)
    if "TP" in text:
        array = _expand_tp_ranges(array)

    sl, tps = _extract_sl_and_tps(array)

    # market order wipe
    if len(price) < 3 or "MKO" in text:
        price = ""

    sl, tps = _apply_pips(sl, tps, sl_in_pips, tp_in_pips)

    # ── build command string (desktop-app compatible) ─────────────────────────
    # Format: /open SYMBOL,DIR,PRICE,SL,TP1,TP2,...,MSG_ID,CHANNEL_ID,CHANNEL
    tp_part = ",".join(tps) if tps else "0"
    command = (
        f"/open {symbol},{direction},{price},{sl},{tp_part},"
        f"{msg_id},{channel_id},{channel}"
    )

    return _make_result(
        kind        = "open",
        command     = command,
        symbol      = symbol,
        direction   = direction,
        entry_price = price,
        sl          = sl,
        tps         = tps,
        msg_id      = msg_id,
        channel_id  = channel_id,
        channel     = channel,
    )


# ---------------------------------------------------------------------------
# edit_open
# ---------------------------------------------------------------------------

def edit_open(
    text: str,
    msg_id: str,
    channel_id: str,
    sl_in_pips: bool,
    tp_in_pips: bool,
    fxlist: list[str] | None = None,
    affixes: set[str] | None = None,
) -> dict:
    """
    Parse an edited Telegram message that modifies an open trade.

    Command format: /edit SYMBOL,DIR,SL,TP1,TP2,...,MSG_ID
    """
    if fxlist is None:
        fxlist = DEF_FXLIST

    array     = text.split("\n")
    symbol    = _resolve_symbol(text, fxlist, affixes)
    direction = "BUY" if "BUY" in text else ("SELL" if "SELL" in text else "")

    array = _split_tp_lines(array)
    if "TP" in text:
        array = _expand_tp_ranges(array)

    sl, tps = _extract_sl_and_tps(array)

    # edit sentinel: "-1" means "no change" (different from open's "0")
    if sl == "0":
        sl = "-1"
    if not tps:
        tps = ["-1"]

    if sl_in_pips and sl != "-1":
        sl = sl + " pips"
    if tp_in_pips:
        tps = [(v + " pips") if v != "-1" else "-1" for v in tps]

    tp_part = ",".join(tps)
    command = f"/edit {symbol},{direction},{sl},{tp_part},{msg_id}"

    return _make_result(
        kind      = "edit",
        command   = command,
        symbol    = symbol,
        direction = direction,
        sl        = sl,
        tps       = tps,
        msg_id    = msg_id,
        channel_id= channel_id,
        channel   = "",
        new_sl    = sl,
        new_tps   = tps,
    )


# ---------------------------------------------------------------------------
# channel_close
# ---------------------------------------------------------------------------

def channel_close(
    text: str,
    msg_id: str,
    tp: str | None = None,
    fxlist: list[str] | None = None,
    affixes: set[str] | None = None,
) -> dict:
    """
    Build a /close command.

    Command format: /close SYMBOL,MSG_ID[,TP_LABEL]
    e.g.  /close USDJPY,5,TP1
    """
    if fxlist is None:
        fxlist = DEF_FXLIST

    body   = text.split("REPLY:")[0]
    symbol = _resolve_symbol(body, fxlist, affixes)
    command = f"/close {symbol},{msg_id},{tp}" if tp else f"/close {symbol},{msg_id}"

    return _make_result(
        kind      = "close",
        command   = command,
        symbol    = symbol,
        msg_id    = msg_id,
        close_tp  = tp or "",
    )


# ---------------------------------------------------------------------------
# channel_close_all / channel_delete_all
# ---------------------------------------------------------------------------

def channel_close_all(msg_id: str = "", channel_id: str = "") -> dict:
    return _make_result(
        kind    = "closeall",
        command = "/closeall",
        msg_id  = msg_id,
        channel_id = channel_id,
    )


def channel_delete_all(msg_id: str = "", channel_id: str = "") -> dict:
    return _make_result(
        kind    = "deleteall",
        command = "/deleteall",
        msg_id  = msg_id,
        channel_id = channel_id,
    )


# ---------------------------------------------------------------------------
# Half / partial close helpers
# ---------------------------------------------------------------------------

def _half_or_partial(
    command_name: str,
    kind: str,
    text: str,
    msg_id: str,
    fxlist: list[str] | None,
    affixes: set[str] | None,
) -> dict:
    if fxlist is None:
        fxlist = DEF_FXLIST
    body   = text.split("REPLY:")[0]
    symbol = _resolve_symbol(body, fxlist, affixes)
    command = f"/{command_name} {symbol},{msg_id}"
    return _make_result(kind=kind, command=command, symbol=symbol, msg_id=msg_id)


def channel_close_partial(text, msg_id, fxlist=None, affixes=None) -> dict:
    return _half_or_partial("closepartial", "closepartial", text, msg_id, fxlist, affixes)


def channel_close_partial_be(text, msg_id, fxlist=None, affixes=None) -> dict:
    return _half_or_partial("closepartialbe", "closepartialbe", text, msg_id, fxlist, affixes)


def channel_close_half(text, msg_id, fxlist=None, affixes=None) -> dict:
    return _half_or_partial("closehalf", "closehalf", text, msg_id, fxlist, affixes)


def channel_close_half_be(text, msg_id, fxlist=None, affixes=None) -> dict:
    return _half_or_partial("closehalfbe", "closehalfbe", text, msg_id, fxlist, affixes)


def channel_breakeven(text, msg_id, fxlist=None, affixes=None) -> dict:
    return _half_or_partial("breakeven", "breakeven", text, msg_id, fxlist, affixes)


def channel_delete(text, msg_id, fxlist=None, affixes=None) -> dict:
    return _half_or_partial("delete", "delete", text, msg_id, fxlist, affixes)


# ---------------------------------------------------------------------------
# channel_update
# ---------------------------------------------------------------------------

def channel_update(
    text: str,
    msg_id: str,
    tp_selection: str = "ALL",
    sl_p: bool = True,
    fxlist: list[str] | None = None,
    affixes: set[str] | None = None,
) -> dict | None:
    """
    Build an /edit or /update command from a reply that modifies SL/TP.

    Returns None when no actionable update is found.
    """
    if fxlist is None:
        fxlist = DEF_FXLIST

    main_body  = text.split("REPLY:")[0]
    reply_body = text.split("REPLY:")[1] if "REPLY:" in text else ""
    symbol     = _resolve_symbol(main_body, fxlist, affixes)

    direction = ""
    for line in main_body.split("\n"):
        if "BUY"  in line: direction = "BUY"
        if "SELL" in line: direction = "SELL"

    price_sl  = "-1"
    price_tp  = "-1"
    tp_prices = ["-1"] * 5
    found_sl  = False
    found_tp  = False

    for line in reply_body.split("\n"):
        if "SET SP" in line:
            found_sl = True
            m = re.search(r"(?<!\S)SET SP.*?(\d+\.?\d*)", line)
            price_sl = m.group(1) if m else "0"
        if "SET PP" in line:
            found_tp = True
            m = re.search(r"(?<!\S)SET PP.*?(\d+\.?\d*)", line)
            price_tp = m.group(1) if m else "0"

    tp_info = ""
    if tp_selection != "ALL":
        for tp_level, tp_price in re.findall(r"MOVE TP(\d)[\s:]*?(\d+\.\d+|\d+)", reply_body):
            lvl = int(tp_level)
            if 1 <= lvl <= 5:
                tp_prices[lvl - 1] = tp_price
        if any(v != "-1" for v in tp_prices):
            tp_info = ",".join(tp_prices)

    if found_sl or found_tp or tp_info:
        if found_sl and found_tp:
            command  = f"/edit {symbol},{direction},{price_sl},{price_tp},-1,-1,-1,-1,{msg_id},update"
            new_tps  = [price_tp]
        elif tp_info:
            sl_part = price_sl if found_sl else "-1"
            command = f"/edit {symbol},{direction},{sl_part},{tp_info},{msg_id},update"
            new_tps = [v for v in tp_prices if v != "-1"]
        else:
            price = price_sl if found_sl else price_tp
            sltp  = "SL" if found_sl else "TP"
            command = f"/update {symbol},{direction},{sltp},{price},{msg_id}"
            new_tps = [] if found_sl else [price]

        return _make_result(
            kind      = "update",
            command   = command,
            symbol    = symbol,
            direction = direction,
            msg_id    = msg_id,
            new_sl    = price_sl if found_sl else "",
            new_tps   = new_tps,
        )

    if not sl_p:
        command = f"/update {symbol},{direction},SL,0,{msg_id}"
        return _make_result(
            kind      = "update",
            command   = command,
            symbol    = symbol,
            direction = direction,
            msg_id    = msg_id,
            new_sl    = "0",
        )

    return None


# ---------------------------------------------------------------------------
# multi_signal
# ---------------------------------------------------------------------------

def multi_signal(
    lines: list[str],
    signal_keywords: set[str],
    alias_key: str,
    alias_values: str,
) -> list[str]:
    """
    When a single message contains multiple BUY/SELL directives produce one
    text block per trade direction.
    """
    for idx, line in enumerate(lines):
        for item in alias_values.split(","):
            item = item.strip()
            if item and item in line:
                lines[idx] = line.replace(item, alias_key)

    signal_pattern  = re.compile(r"\b(" + "|".join(re.escape(w) for w in signal_keywords) + r")\b")
    enprice_pattern = re.compile(r"ENPRICE\s*\d+\.?\d*", re.IGNORECASE)

    total   = len([ln for ln in lines if signal_pattern.search(ln)])
    results: list[str] = []

    for target_idx in range(total):
        bs_seen = ep_seen = 0
        modified: list[str] = []

        for line in lines:
            bs_match = signal_pattern.search(line)
            if bs_match:
                if bs_seen != target_idx:
                    line = line.replace(bs_match.group(), "")
                bs_seen += 1

            ep_match = enprice_pattern.search(line)
            if ep_match:
                if ep_seen != target_idx:
                    line = line.replace(ep_match.group(), "")
                ep_seen += 1

            cleaned = re.sub(r"\s{2,}", " ", line).strip()
            if cleaned:
                modified.append(cleaned)

        results.append("\n".join(modified))

    return results


# ---------------------------------------------------------------------------
# preprocess_text
# ---------------------------------------------------------------------------

def preprocess_text(
    raw_text: str,
    msg_items: list[tuple],
    og_text_indices: list[int] | None = None,
    delimiter_item_index: int = 33,
) -> str:
    """
    Apply keyword substitution and delimiter removal before routing.

    Returns uppercased, normalised text ready for ``route_signal()``.
    """
    if og_text_indices is None:
        og_text_indices = [0, 1, 2, 3, 4, 22, 23, 24, 25, 26]

    try:
        _, delimiters = msg_items[delimiter_item_index]
        if delimiters and len(delimiters) == 2:
            escaped = [re.escape(d) for d in delimiters]
            raw_text = re.sub(f"{escaped[0]}.*?{escaped[1]}", "", raw_text)
    except (IndexError, TypeError):
        pass

    stext            = " " + raw_text.upper()
    stext_normalized = normalize_text(stext).upper()

    for i in og_text_indices:
        try:
            key, value = msg_items[i]
        except IndexError:
            continue
        if not value:
            continue
        for item in value.split(","):
            if i == 0:
                stext            = stext.replace(item, key, 1)
                stext_normalized = stext_normalized.replace(item, key, 1)
            else:
                stext            = stext.replace(item, key)
                stext_normalized = stext_normalized.replace(item, key)

    return stext_normalized


# ---------------------------------------------------------------------------
# split_entry_values
# ---------------------------------------------------------------------------

def split_entry_values(entry: str) -> list[str]:
    """Split a price-range string on ``/``, ``-``, ``_``."""
    if not isinstance(entry, str):
        return []
    return [p.strip() for p in re.split(r"[\/\-\_]", entry) if p.strip()]


# ---------------------------------------------------------------------------
# route_signal  –  top-level dispatcher
# ---------------------------------------------------------------------------

def route_signal(
    text: str,
    msg_id: str,
    channel_id: str,
    channel_name: str,
    msg_items: list[tuple],
    signal_keywords: set[str],
    replied_text: str | None = None,
    fxlist: list[str] | None = None,
    affixes: set[str] | None = None,
) -> list[dict]:
    """
    Top-level dispatcher.  Mirrors ``App.on_message`` routing logic.

    Parameters
    ----------
    text            : pre-processed (uppercased) message text
    msg_id          : Telegram message ID string
    channel_id      : channel numeric ID string
    channel_name    : channel display name (truncated to 8 chars internally)
    msg_items       : list(selectedChannel['msg'].items())
    signal_keywords : set of BUY/SELL keyword strings
    replied_text    : pre-processed replied-to message text, or None
    fxlist          : optional symbol list override
    affixes         : optional affix set

    Returns
    -------
    List of result dicts (see ``_make_result`` for the full schema).
    Every dict has these keys — always present, unused ones are "":

        kind         – "open" | "edit" | "close" | "closeall" | "deleteall"
                       "closehalf" | "closehalfbe" | "closepartial"
                       "closepartialbe" | "update" | "breakeven" | "delete"
        command      – full command string  e.g. /open XAUUSD,BUY,2330,...
        symbol       – instrument symbol
        direction    – "BUY" | "SELL" | ""
        entry_price  – entry price string  ("" = market order)
        sl           – stop-loss string
        tps          – list of TP value strings  (dynamic length)
        msg_id       – Telegram message ID
        channel_id   – channel numeric ID
        channel      – channel name (8-char)
        close_tp     – "TP1" / "TP2" / … when closing a partial TP
        new_sl       – new SL value for update/edit kinds
        new_tps      – new TP values list for update/edit kinds
    """
    results: list[dict] = []

    def _item(index: int, default=None):
        try:
            return msg_items[index][1]
        except IndexError:
            return default

    def _int_item(index: int, default: int = 0) -> int:
        try:
            return int(_item(index, default))
        except (TypeError, ValueError):
            return default

    price_rng    = _int_item(29, 0)
    sl_in_pips   = bool(_item(30, False))
    tp_in_pips   = bool(_item(31, False))
    bothorder    = bool(_item(34, False))
    alias_key    = msg_items[0][0] if msg_items else " BUY"
    alias_values = _item(0, "") or ""

    short_channel = channel_name[:8]

    # ── A) Fresh message (no reply) ──────────────────────────────────────────
    if replied_text is None:
        contains_signal = any(kw in text for kw in signal_keywords)
        ignore_signal   = "TIGNORE" in text

        if contains_signal and not ignore_signal:

            if price_rng == 3:
                # Emit one result per price in the range
                raw_price = extract_entry_price(text, fxlist=fxlist, affixes=affixes)
                entries   = split_entry_values(raw_price) or [""]
                for entry_val in entries:
                    res = channel_open(
                        text, msg_id, channel_id,
                        price_rng=0,
                        sl_in_pips=sl_in_pips, tp_in_pips=tp_in_pips,
                        channel=short_channel,
                        fxlist=fxlist, affixes=affixes,
                        entry_override=entry_val or None,
                    )
                    results.append(res)

            else:
                lines          = text.split("\n")
                buy_sell_lines = [ln for ln in lines if any(kw in ln for kw in signal_keywords)]

                if not bothorder or len(buy_sell_lines) < 2:
                    results.append(channel_open(
                        text, msg_id, channel_id, price_rng,
                        sl_in_pips, tp_in_pips, short_channel,
                        fxlist=fxlist, affixes=affixes,
                    ))
                else:
                    for modified_text in multi_signal(lines, signal_keywords, alias_key, alias_values):
                        if modified_text:
                            results.append(channel_open(
                                " " + modified_text, msg_id, channel_id, price_rng,
                                sl_in_pips, tp_in_pips, short_channel,
                                fxlist=fxlist, affixes=affixes,
                            ))

        if "CLZP" in text and "TIGNORE" not in text:
            results.append(channel_close_all(msg_id, channel_id))

        if "DZD" in text and "TIGNORE" not in text:
            results.append(channel_delete_all(msg_id, channel_id))

        return results

    # ── B) Reply message (modify / close an existing trade) ──────────────────
    reply_text  = text
    orig_text   = replied_text
    ignore_flag = "TIGNORE" not in reply_text
    combined    = orig_text + "\nREPLY:\n" + reply_text

    if "TP1 HIT" in reply_text:
        results.append(channel_close(combined, msg_id, "TP1", fxlist, affixes))
    if "TP2 HIT" in reply_text:
        results.append(channel_close(combined, msg_id, "TP2", fxlist, affixes))
    if "TP3 HIT" in reply_text:
        results.append(channel_close(combined, msg_id, "TP3", fxlist, affixes))
    if "TP4 HIT" in reply_text:
        results.append(channel_close(combined, msg_id, "TP4", fxlist, affixes))

    if "CLFL" in reply_text and "CLHF" not in reply_text and "CLPT" not in reply_text and ignore_flag:
        results.append(channel_close(combined, msg_id, fxlist=fxlist, affixes=affixes))

    if "CLHF" in reply_text and ignore_flag:
        fn = channel_close_half_be if "MSENTRY" in reply_text else channel_close_half
        results.append(fn(combined, msg_id, fxlist, affixes))

    if "CLPT" in reply_text and ignore_flag:
        fn = channel_close_partial_be if "MSENTRY" in reply_text else channel_close_partial
        results.append(fn(combined, msg_id, fxlist, affixes))

    if (
        "MSENTRY" not in reply_text
        and "CLFL"  not in reply_text
        and ("MOVE TP" in reply_text or "SET SP" in reply_text
             or "SET PP" in reply_text or "RMVSL" in reply_text)
    ):
        tp_sel = "TP" if "MOVE TP" in reply_text else "ALL"
        sl_p   = "RMVSL" not in reply_text
        res    = channel_update(combined, msg_id, tp_sel, sl_p, fxlist, affixes)
        if res:
            results.append(res)

    if (
        "MSENTRY" in reply_text
        and "CLFL" not in reply_text
        and "CLHF" not in reply_text
        and "CLPT" not in reply_text
    ):
        results.append(channel_breakeven(combined, msg_id, fxlist, affixes))

    if "DZF" in reply_text:
        results.append(channel_delete(combined, msg_id, fxlist, affixes))

    if "AGAINENTER" in reply_text and ignore_flag:
        results.append(channel_open(
            orig_text, msg_id, channel_id,
            price_rng  = _int_item(29, 0),
            sl_in_pips = sl_in_pips,
            tp_in_pips = tp_in_pips,
            channel    = short_channel,
            fxlist     = fxlist,
            affixes    = affixes,
        ))

    return results