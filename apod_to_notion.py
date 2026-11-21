# -*- coding: utf-8 -*-
"""
apod_to_notion.py  (v2：自动翻译版)
====================================
每天做这几件事：
  1. 从 NASA 拿到今天的 APOD（每日天文图）
  2. 如果 Notion 里已经有这一天，就跳过
  3. 把英文解释分成 3 段，交给大模型（默认 DeepSeek）翻译成中文
  4. （可选）让大模型从你已有的选项里挑 Object Type / Sub / Constellation
  5. 按你自己的页面排版，在 Notion 数据库里新建一页：
       左英右中的双栏 ×3 → 分割线 → Credit → 来源链接 → 分割线 → ✨ Insight 提示框

需要的环境变量（也可以写进同目录的 .env 文件）：
    NASA_API_KEY        NASA 的 key（https://api.nasa.gov）
    NOTION_TOKEN        Notion 集成密钥（ntn_ 开头）
    NOTION_DATABASE_ID  数据库 ID（32 位）
    LLM_API_KEY         大模型的 key（默认 DeepSeek）
    LLM_BASE_URL        可选，默认 https://api.deepseek.com
    LLM_MODEL           可选，默认 deepseek-flash
    CLASSIFY            可选，填 0 就不自动分类

用法：
    python apod_to_notion.py              # 处理今天
    python apod_to_notion.py 2026-10-19   # 补某一天（最近几周内的）
只需要一个第三方库：requests（pip install requests）
"""

import datetime  # 日期
import html      # 把 &amp; 这类网页转义字符还原
import itertools # 列出所有组合（用来挑切点）
import json      # 处理 JSON
import os        # 读取环境变量、文件路径
import re        # 正则表达式：在网页里"按规律找东西"
import sys       # 读取命令行参数、出错时退出
import time      # 重试前等几秒

import requests  # 发送网络请求


# ======================================================================
# 第 0 部分：配置
# ======================================================================
NASA_API_URL = "https://api.nasa.gov/planetary/apod"
APOD_HOME_URL = "https://science.nasa.gov/apod/"            # 新官网首页
APOD_ARCHIVE_URL = "https://science.nasa.gov/apod/archive/"  # 新官网存档页
NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-chat"   # DeepSeek 当前的模型名（2026-10 官网文档）

# 数据库列名（要和 Notion 里一字不差）
PROP_TITLE = "Daily APOD"
PROP_DATE = "Date"
PROP_FILES = "Files & media"
PROP_TYPE = "Object Type"
PROP_SUB = "Object Type - Sub"
PROP_CONST = "Constellation"
PROP_INSIGHTS = "Insights"

PARAGRAPHS = 3            # 你的排版：英文分 3 段
NOTION_TEXT_LIMIT = 2000  # Notion 一段文字最多 2000 字符

# —— 你数据库里已有的选项（大模型只能从这里面选，选不准就留空）——
OBJECT_TYPES = ["Earth & Sky", "Spaceflight", "Solar System", "Deep Sky", "Other"]
OBJECT_SUBS = {  # 每个大类下常用的小类
    "Earth & Sky": ["Aurora", "Eclipse", "Landscape", "Skyscape",
                    "Noctilucent Cloud/Airglow", "Milky Way/Star Trails"],
    "Spaceflight": ["ISS", "Launch", "Historical Archive", "Spacecraft/Telescope"],
    "Solar System": ["Sun", "Moon", "Planet", "Moon/Satellite", "Meteor", "Asteroid", "Comet"],
    "Deep Sky": ["SNR", "Nebula", "Cluster", "Galaxy", "Large-scale Structure"],
    "Other": ["Other"],
}
CONSTELLATIONS = [
    "non-fixed", "Andromeda 仙女座", "Antlia 唧筒座", "Apus 天燕座", "Aquarius 宝瓶座",
    "Aquila 天鹰座", "Ara 天坛座", "Aries 白羊座", "Auriga 御夫座", "Boötes 牧夫座",
    "Caelum 雕具座", "Camelopardalis 鹿豹座", "Cancer 巨蟹座", "Canes Venatici 猎犬座",
    "Canis Major 大犬座", "Canis Minor 小犬座", "Capricornus 摩羯座", "Carina 船底座",
    "Cassiopeia 仙后座", "Centaurus 半人马座", "Cepheus 仙王座", "Cetus 鲸鱼座",
    "Chamaeleon 蝘蜓座", "Circinus 圆规座", "Columba 天鸽座", "Coma Berenices 后发座",
    "Corona Australis 南冕座", "Corona Borealis 北冕座", "Corvus 乌鸦座", "Crater 巨爵座",
    "Crux 南十字座", "Cygnus 天鹅座", "Delphinus 海豚座", "Dorado 剑鱼座", "Draco 天龙座",
    "Equuleus 小马座", "Eridanus 波江座", "Fornax 天炉座", "Gemini 双子座", "Grus 天鹤座",
    "Hercules 武仙座", "Horologium 时钟座", "Hydra 长蛇座", "Hydrus 水蛇座", "Indus 印第安座",
    "Lacerta 蝎虎座", "Leo 狮子座", "Leo Minor 小狮子座", "Lepus 天兔座", "Libra 天秤座",
    "Lupus 豺狼座", "Lynx 天猫座", "Lyra 天琴座", "Mensa 山案座", "Microscopium 显微镜座",
    "Monoceros 麒麟座", "Musca 苍蝇座", "Norma 矩尺座", "Octans 南极座", "Ophiuchus 蛇夫座",
    "Orion 猎户座", "Pavo 孔雀座", "Pegasus 飞马座", "Perseus 英仙座", "Phoenix 凤凰座",
    "Pictor 绘架座", "Pisces 双鱼座", "Piscis Austrinus 南鱼座", "Puppis 船尾座",
    "Pyxis 罗盘座", "Reticulum 网罟座", "Sagitta 天箭座", "Sagittarius 人马座(射手)",
    "Scorpio 天蝎座", "Sculptor 玉夫座", "Scutum 盾牌座", "Serpens 巨蛇座", "Sextans 六分仪座",
    "Taurus 金牛座", "Telescopium 望远镜座", "Triangulum 三角座", "Triangulum Australe 南三角座",
    "Tucana 杜鹃座", "Ursa Major 大熊座", "Ursa Minor 小熊座", "Vela 船帆座",
    "Virgo 室女座(处女)", "Volans 飞鱼座", "Vulpecula 狐狸座",
]

# —— 翻译规则（系统提示词）：把你的翻译习惯写成规则交给大模型 ——
TRANSLATE_PROMPT = """你是资深天文科普译者（风格参考《中国国家天文》与专业天文馆解说词）。请将用户提供的 N 段英文 APOD 解说逐段译为自然、流畅、优雅的简体中文。

翻译准则：
1. 语序重组（核心）：彻底摆脱英文被动语态与长定语从句的束缚，按中文表达习惯拆分或重排语序，做到信达雅，杜绝机翻腔（例如不要直译成“最亮的星位于中心左侧，是蓝色的……”，而应译为“画面中心偏左最亮的那颗蓝星是……”）。
2. 专有名词规范：天体、星座、深空天体、星表编号及望远镜名称统一采用中国天文学名词审定委员会的标准译名（如 Alnitak 译为“参宿一”，Orion's Belt 译为“猎户座腰带”）。
3. 排版克制：标准中文天体名直接融入行文，不要在中文后面强行用括号附带英文原名，也不要在中文词前后刻意加空格；仅保留无公认中文译名的冷门专名或星表编号（如 NGC 2023），且中文与英文字母/数字之间保留常规阅读间距即可。
4. 精确严谨：距离、尺度、年份、光谱波段等科学数据必须严格准确，不做随意换算或删减。
5. 纯净输出：译文中不得出现任何超链接或 Markdown 格式符号（如 **、[] 等）。
6. 严格对齐：输出段落数量必须严格等于输入的 N 段，严禁合并或拆散段落。

只输出合法 JSON，格式为：{"zh": ["第1段译文", "第2段译文", ...]}"""

CLASSIFY_PROMPT = """你帮我给一张 APOD 天文图分类。只能从给定选项里选，拿不准就留空。
输出 JSON：{"object_type": "选项或空字符串", "object_sub": ["0到3个选项"], "constellation": ["0到2个选项"]}
规则：
- object_type 只能是：%s
- object_sub 只能从该大类的小类里选：%s
- constellation 只能从这个列表里选：%s
- 太阳系天体、地景/天空景观、航天器等位置不固定在某个星座的，constellation 填 ["non-fixed"]。
- 深空天体只有在文字明确写出星座、或你非常确定时才填星座，否则留空 []。"""


# ======================================================================
# 第 1 部分：读取配置（环境变量 + .env 文件）
# ======================================================================
def load_dotenv(path=".env"):
    """
    手动读取 .env 文件（每行 KEY=VALUE），不需要额外安装库。
    已经在系统里设置过的环境变量优先，不会被覆盖。
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue  # 跳过空行、注释、格式不对的行
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get_env(name, default=None):
    """读取环境变量；必填的没设置就提示并退出。"""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if default is not None:
        return default
    print(f"❌ 没有找到环境变量 {name}，请写进 .env 文件或设置环境变量（见 教程.md）")
    sys.exit(1)


def is_proxy_error(exc):
    """代理没开、端口不对，或 HTTPS_PROXY 误写成 https:// 时，requests 常报这类错。"""
    if isinstance(exc, requests.exceptions.ProxyError):
        return True
    text = str(exc).lower()
    return "unable to connect to proxy" in text or "ssleoferror" in text or "eof occurred in violation of protocol" in text


SESSION = requests.Session()  # 整个脚本共用一个会话；代理失败后会改成直连


def http_request(method, url, **kwargs):
    """发 HTTP 请求。若系统/环境代理连不上，自动改直连再试一次。"""
    kwargs.setdefault("timeout", 30)
    try:
        return SESSION.request(method, url, **kwargs)
    except requests.RequestException as e:
        if SESSION.trust_env is False or not is_proxy_error(e):
            raise
        print("⚠️ 系统或环境变量里的代理连不上（报错里的 443 是 HTTPS 端口，不是 NASA 的错误码）。改直连再试一次 ...")
        SESSION.trust_env = False
        SESSION.proxies = {"http": None, "https": None}
        return SESSION.request(method, url, **kwargs)




# ======================================================================
# 第 2 部分：获取 APOD（接口 + 新官网网页）
# ======================================================================
def target_date():
    """命令行给了日期就用它，否则用今天（UTC）。"""
    if len(sys.argv) > 1:
        return sys.argv[1]
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def fetch_api(api_key, date_str, retries=3):
    """
    调 NASA 接口拿英文解释（纯文字）。必须带 date，不带会经常 500。
    注意：2026 年搬家后，接口给的标题/图片经常是错的（"NASA Science" + logo），
    所以这里只用它的 explanation（作为网页解析失败时的备用）。失败时返回 None，后面用网页兜底。
    """
    params = {"api_key": api_key, "date": date_str, "thumbs": "true"}
    for attempt in range(1, retries + 1):
        try:
            resp = http_request("get", NASA_API_URL, params=params)
            if resp.status_code == 200:
                return resp.json()
            print(f"⚠️ NASA 接口第 {attempt} 次失败：HTTP {resp.status_code}")
        except requests.RequestException as e:
            print(f"⚠️ NASA 接口第 {attempt} 次网络错误：{e}")
        time.sleep(5)
    return None


def find_article_url(date_str):
    """在新官网首页/存档页里，找到这一天的文章网址。"""
    d = datetime.date.fromisoformat(date_str)
    months = ["january", "february", "march", "april", "may", "june", "july",
              "august", "september", "october", "november", "december"]
    pattern = (r'https://science\.nasa\.gov/image-article/(?:apod/)?apod-'
               + f"{d.year}-{months[d.month - 1]}-0?{d.day}-" + r'[^"\s]+')
    for page_url in (APOD_HOME_URL, APOD_ARCHIVE_URL):
        page = http_request("get", page_url).text
        m = re.search(pattern, page)
        if m:
            return m.group(0)
    return None


def find_meta(page, prop):
    """读取 <meta property="og:xxx" content="...">。"""
    m = re.search(r'<meta property="' + re.escape(prop) + r'" content="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else None


def html_to_segments(fragment):
    """
    把一小段 HTML 变成"片段列表"：[{"text": "...", "url": 链接或None}, ...]
    只保留 http(s) 链接（mailto 之类会被 Notion 拒绝，当普通文字处理）。
    """
    segments = []
    # 按 <a ...>...</a> 切开：链接部分和普通部分交替出现
    parts = re.split(r'(<a\s[^>]*href="[^"]*"[^>]*>.*?</a>)', fragment, flags=re.S)
    for part in parts:
        m = re.match(r'<a\s[^>]*href="([^"]*)"[^>]*>(.*?)</a>', part, flags=re.S)
        url = html.unescape(m.group(1)) if m else None
        inner = m.group(2) if m else part
        text = html.unescape(re.sub(r"<[^>]+>", "", inner))  # 去掉其余标签
        text = re.sub(r"\s+", " ", text)                     # 合并多余空白
        if url and not url.startswith("http"):
            url = None
        if text:
            # 两个链接紧挨着（如 "ASTRON""LOFAR"）时，中间补一个空格
            if url and segments and segments[-1]["url"] and not segments[-1]["text"].endswith(" "):
                segments.append({"text": " ", "url": None})
            segments.append({"text": text, "url": url})
    # 去掉开头结尾空格
    if segments:
        segments[0]["text"] = segments[0]["text"].lstrip()
        segments[-1]["text"] = segments[-1]["text"].rstrip()
    return [s for s in segments if s["text"]]


def fetch_article(article_url):
    """从文章网页里取：标题、图片、带链接的解释、带链接的 Credit。"""
    page = http_request("get", article_url).text
    info = {"article_url": article_url}

    # 标题："APOD: 2026 October 19 - Treble Clef: ... - NASA Science" → 去掉前后缀
    title = find_meta(page, "og:title") or ""
    title = re.sub(r"^APOD:\s*\d{4}\s+\w+\s+\d{1,2}\s*[-–—]\s*", "", title)
    title = re.sub(r"\s*[-–—]\s*NASA Science$", "", title)
    info["title"] = title.strip()
    info["image"] = find_meta(page, "og:image")

    # 解释："<strong>Explanation:</strong> ...<br><br><strong>Tomorrow's picture"
    m = re.search(r"<strong>\s*Explanation:?\s*</strong>(.*?)(?:<br\s*/?>\s*<br\s*/?>|</p>)", page, re.S)
    if m:
        body = re.sub(r"^\s*Explanation\s*:\s*", "", m.group(1))  # 有时会重复一个 "Explanation :"
        info["explanation_segments"] = html_to_segments(body)

    # Credit：表格里标题含 "Credit" 的那一行（"Credit:"、"Credit & Copyright" 等）
    c = re.search(r"<th[^>]*>\s*(?:Image\s+)?Credit[^<]*</th>\s*<td[^>]*>(.*?)</td>", page, re.S)
    if c:
        credit = html_to_segments(c.group(1))
        if credit:  # 有时内容自己又以 "Image Credit:" 开头，去掉免得重复
            credit[0]["text"] = re.sub(r"^(Image\s+)?Credit\s*(&\s*Copyright)?\s*:\s*", "", credit[0]["text"])
        info["credit_segments"] = [x for x in credit if x["text"]]

    # 视频：网页里嵌了 YouTube 播放器，就说明今天是视频（接口的 media_type 不可靠）
    v = re.search(r'https://www\.youtube\.com/embed/([\w-]+)', page)
    if v:
        info["video_url"] = "https://www.youtube.com/watch?v=" + v.group(1)
    return info


def get_apod(api_key, date_str):
    """把接口和网页的数据合在一起，返回一个字典。"""
    api = fetch_api(api_key, date_str) or {}
    article_url = find_article_url(date_str)
    if not article_url:
        print(f"❌ 新官网上找不到 {date_str} 的文章（可能还没发布），今天先跳过")
        sys.exit(1)
    art = fetch_article(article_url)

    segments = art.get("explanation_segments")
    if not segments:  # 网页没解析出来，就用接口的纯文字（没有链接）
        text = api.get("explanation", "").split("Tomorrow's picture")[0].strip()
        segments = [{"text": text, "url": None}] if text else []
    if not segments:
        print("❌ 接口和网页都没拿到解释文字，放弃")
        sys.exit(1)

    return {
        "date": date_str,
        "title": art["title"] or api.get("title", ""),
        "media_type": "video" if art.get("video_url") else "image",
        "image": art.get("image"),
        "video_url": art.get("video_url"),
        "segments": segments,
        "credit": art.get("credit_segments") or [{"text": api.get("copyright", "NASA"), "url": None}],
        "article_url": article_url,
    }


# ======================================================================
# 第 3 部分：把英文分成 3 段（按句子切，并保留链接）
# ======================================================================
def split_segments(segments, n=PARAGRAPHS):
    """
    NASA 的解释是一整段。这里在"句号后面"找切点，切成长度差不多的 n 段。
    segments 里带着链接，切的时候不能把一个链接切断。
    返回：[[片段, 片段, ...], [...], [...]]
    """
    full = "".join(s["text"] for s in segments)

    # 1) 找出所有链接所在的位置，切点不能落在链接里面
    link_ranges, pos = [], 0
    for s in segments:
        if s["url"]:
            link_ranges.append((pos, pos + len(s["text"])))
        pos += len(s["text"])

    # 2) 候选切点：". " "? " "! " 之后、下一个字母大写（避开 "et al. " 这种情况）
    cuts = []
    for m in re.finditer(r'[.!?]["\')]?\s+(?=[A-Z"\'(\[])', full):
        cut = m.end()
        before = full[max(0, cut - 8):cut]
        if re.search(r"\b(al|e\.g|i\.e|vs|Mr|Dr|St|Mt|approx)\.\s*$", before):
            continue
        if any(a < cut < b for a, b in link_ranges):
            continue
        cuts.append(cut)

    # 3) 在所有候选切点组合里，选"最长那段最短"的一种，让 n 段尽量一样长
    #    （itertools.combinations 会列出"从 cuts 里挑 n-1 个"的所有挑法）
    best = []
    for combo in itertools.combinations(cuts, min(n - 1, len(cuts))):
        b = [0, *combo, len(full)]
        longest = max(y - x for x, y in zip(b, b[1:]))
        if not best or longest < best[0]:
            best = [longest, list(combo)]
    chosen = best[1] if best else []
    bounds = [0] + chosen + [len(full)]

    # 4) 按切点把片段分配到每一段
    paragraphs = []
    for start, end in zip(bounds, bounds[1:]):
        para, pos = [], 0
        for s in segments:
            s_start, s_end = pos, pos + len(s["text"])
            pos = s_end
            a, b = max(start, s_start), min(end, s_end)
            if a < b:
                para.append({"text": s["text"][a - s_start:b - s_start], "url": s["url"]})
        if para:
            para[0]["text"] = para[0]["text"].lstrip()
            para[-1]["text"] = para[-1]["text"].rstrip()
            paragraphs.append([p for p in para if p["text"]])
    return paragraphs


def plain(paragraph):
    """一段的纯文字（给大模型翻译用）。"""
    return "".join(s["text"] for s in paragraph)


# ======================================================================
# 第 4 部分：调用大模型（OpenAI 兼容接口：DeepSeek / 通义千问 / Kimi 都行）
# ======================================================================
def chat_json(system_prompt, user_text):
    """发一次对话请求，要求模型只回 JSON，返回解析后的字典。"""
    base_url = get_env("LLM_BASE_URL", DEFAULT_LLM_BASE_URL).rstrip("/")
    body = {
        "model": get_env("LLM_MODEL", DEFAULT_LLM_MODEL),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "response_format": {"type": "json_object"},  # 要求只输出 JSON
        "temperature": 0.3,                           # 低一点，翻译更稳定
        "max_tokens": 4000,
    }
    if "deepseek" in base_url:
        body["thinking"] = {"type": "disabled"}  # DeepSeek 默认会"思考"，关掉更快更省钱
    resp = http_request(
        "post",
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {get_env('LLM_API_KEY')}",
                 "Content-Type": "application/json"},
        json=body, timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"大模型接口 HTTP {resp.status_code}: {resp.text[:300]}")
    content = resp.json()["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", content, re.S)  # 防止模型在 JSON 前后多说话
    return json.loads(m.group(0) if m else content)


def translate(paragraphs):
    """把 N 段英文翻成 N 段中文；段数不对就再试一次。"""
    n = len(paragraphs)
    numbered = "\n\n".join(f"[{i + 1}] {plain(p)}" for i, p in enumerate(paragraphs))
    user_text = f"N = {n}\n\n{numbered}"
    for attempt in (1, 2):
        try:
            zh = chat_json(TRANSLATE_PROMPT, user_text).get("zh", [])
            zh = [re.sub(r"^\[\d+\]\s*", "", str(z)).strip() for z in zh]
            if len(zh) == n and all(zh):
                return zh
            print(f"⚠️ 第 {attempt} 次翻译段数不对（要 {n} 段，得到 {len(zh)} 段）")
        except Exception as e:  # 网络错误、JSON 解析失败等
            print(f"⚠️ 第 {attempt} 次翻译失败：{e}")
    print("⚠️ 翻译失败，中文栏先留空，你可以手动补")
    return [""] * n


def classify(apod, english):
    """让大模型从已有选项里挑分类；不在列表里的一律丢掉。失败就全部留空。"""
    empty = {"object_type": None, "object_sub": [], "constellation": []}
    if get_env("CLASSIFY", "1") == "0":
        return empty
    prompt = CLASSIFY_PROMPT % (
        json.dumps(OBJECT_TYPES, ensure_ascii=False),
        json.dumps(OBJECT_SUBS, ensure_ascii=False),
        json.dumps(CONSTELLATIONS, ensure_ascii=False),
    )
    try:
        r = chat_json(prompt, f"Title: {apod['title']}\n\n{english}")
    except Exception as e:
        print(f"⚠️ 自动分类失败（不影响其他内容）：{e}")
        return empty
    t = r.get("object_type") if r.get("object_type") in OBJECT_TYPES else None
    allowed_subs = OBJECT_SUBS.get(t, [])
    return {
        "object_type": t,
        "object_sub": [s for s in r.get("object_sub", []) if s in allowed_subs][:3],
        "constellation": [c for c in r.get("constellation", []) if c in CONSTELLATIONS][:2],
    }


# ======================================================================
# 第 5 部分：拼 Notion 的"块"（照着你的页面排版）
# ======================================================================
def rich_text(segments, bold=False):
    """片段列表 → Notion rich_text（带链接；超过 2000 字自动切开）。"""
    result = []
    for s in segments:
        for i in range(0, len(s["text"]), NOTION_TEXT_LIMIT):
            item = {"type": "text", "text": {"content": s["text"][i:i + NOTION_TEXT_LIMIT]}}
            if s.get("url"):
                item["text"]["link"] = {"url": s["url"]}
            if bold:
                item["annotations"] = {"bold": True}
            result.append(item)
    return result


def seg(text, url=None):
    """快速做一个片段。"""
    return {"text": text, "url": url}


def block(block_type, content=None, children=None):
    """通用的块：block("divider") / block("heading_3", {...})。"""
    data = content or {}
    if children:
        data["children"] = children
    return {"object": "block", "type": block_type, block_type: data}


def heading3(segments):
    return block("heading_3", {"rich_text": rich_text(segments)})


def two_columns(english_segments, chinese_text):
    """一行双栏：左边英文（带链接），右边中文（不带链接）。"""
    left = block("column", children=[heading3(english_segments)])
    right = block("column", children=[heading3([seg(chinese_text)] if chinese_text else [])])
    return block("column_list", children=[left, right])


def insight_callout():
    """绿色背景 ✨ 提示框：Insight 标题 + 分割线 + 灰色空引用。"""
    return block("callout", {
        "rich_text": [],
        "icon": {"type": "emoji", "emoji": "✨"},
        "color": "green_background",
    }, children=[
        block("heading_2", {"rich_text": rich_text([seg("Insight")], bold=True)}),
        block("divider"),
        block("quote", {"rich_text": [], "color": "gray"}),
    ])


def apod_old_link(date_str):
    """2026-10-19 → https://apod.nasa.gov/apod/ap261019.html"""
    return f"https://apod.nasa.gov/apod/ap{date_str[2:4]}{date_str[5:7]}{date_str[8:10]}.html"


def build_children(apod, paragraphs, chinese):
    children = []
    for en, zh in zip(paragraphs, chinese):
        children.append(two_columns(en, zh))
        children.append(block("divider"))
    children.append(block("paragraph", {"rich_text": rich_text([seg("Credit: ")], bold=True)
                                                    + rich_text(apod["credit"])}))
    children.append(block("paragraph", {"rich_text":
        rich_text([seg("Source: ")], bold=True)
        + rich_text([seg(f"APOD {apod['date']}", apod["article_url"]),
                     seg(" · "),
                     seg(apod_old_link(apod["date"]), apod_old_link(apod["date"]))])}))
    children.append(block("divider"))
    # 10 月下旬之后的页面不再放 ✨ Insight 框。想加回来就把下一行取消注释。
    # children.append(insight_callout())
    return children


def build_properties(apod, cls):
    props = {
        PROP_TITLE: {"title": rich_text([seg(apod["title"])], bold=True)},
        PROP_DATE: {"date": {"start": apod["date"]}},
        PROP_INSIGHTS: {"checkbox": False},
    }
    # 图片放图片链接；视频放 YouTube 链接（和你 10-18 那条一样）
    media = apod.get("video_url") if apod["media_type"] == "video" else apod.get("image")
    if media:
        props[PROP_FILES] = {"files": [{"name": apod["title"][:100], "type": "external",
                                        "external": {"url": media}}]}
    if cls["object_type"]:
        props[PROP_TYPE] = {"select": {"name": cls["object_type"]}}
    if cls["object_sub"]:
        props[PROP_SUB] = {"multi_select": [{"name": s} for s in cls["object_sub"]]}
    if cls["constellation"]:
        props[PROP_CONST] = {"multi_select": [{"name": c} for c in cls["constellation"]]}
    return props


# ======================================================================
# 第 6 部分：Notion 接口
# ======================================================================
def notion_headers():
    return {"Authorization": f"Bearer {get_env('NOTION_TOKEN')}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json"}


def already_exists(database_id, date_str):
    """查重：数据库里有没有 Date = 这一天 的记录。"""
    resp = http_request("post", f"{NOTION_API_URL}/databases/{database_id}/query",
                         headers=notion_headers(),
                         json={"filter": {"property": PROP_DATE, "date": {"equals": date_str}}})
    if resp.status_code != 200:
        print(f"❌ 查询 Notion 失败：HTTP {resp.status_code}\n{resp.text}")
        sys.exit(1)
    return len(resp.json().get("results", [])) > 0


def create_page(database_id, properties, children):
    resp = http_request("post", f"{NOTION_API_URL}/pages", headers=notion_headers(),
                         json={"parent": {"database_id": database_id},
                               "properties": properties, "children": children},
                         timeout=60)
    if resp.status_code != 200:
        print(f"❌ 创建 Notion 页面失败：HTTP {resp.status_code}\n{resp.text}")
        sys.exit(1)
    return resp.json().get("url")


# ======================================================================
# 第 7 部分：主流程
# ======================================================================
def main():
    load_dotenv()
    nasa_key = get_env("NASA_API_KEY")
    database_id = get_env("NOTION_DATABASE_ID")
    get_env("NOTION_TOKEN")
    get_env("LLM_API_KEY")  # 提前检查，缺了就早点报错

    date_str = target_date()
    if already_exists(database_id, date_str):
        print(f"ℹ️ {date_str} 已经在数据库里了，跳过。")
        return

    print(f"🔭 获取 {date_str} 的 APOD ...")
    apod = get_apod(nasa_key, date_str)
    print(f"✅ {apod['title']}")

    paragraphs = split_segments(apod["segments"])
    print(f"✂️ 英文分成了 {len(paragraphs)} 段，开始翻译 ...")
    chinese = translate(paragraphs)
    cls = classify(apod, "\n\n".join(plain(p) for p in paragraphs))
    print(f"🏷️ 分类：{cls}")

    url = create_page(database_id, build_properties(apod, cls),
                      build_children(apod, paragraphs, chinese))
    print(f"🎉 已添加到 Notion：{url}")


if __name__ == "__main__":
    main()
