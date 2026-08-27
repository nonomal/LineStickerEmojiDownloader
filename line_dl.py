#!/usr/bin/env python3
import argparse
import glob
import json
import os
import re
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:
    from requests.packages.urllib3.util.retry import Retry

__version__ = "0.3.0-single"

# ============================================================================
# 文件名净化
# ============================================================================
INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_BYTES = 120
SITE_SUFFIX = re.compile(r"\s*[|｜]\s*LINE\s*STORE\s*$", re.IGNORECASE)
CATEGORY_SUFFIX = re.compile(
    r"\s*[–—-]\s*LINE\s*(?:emoji|emojis|sticker|stickers|絵文字|貼圖|表情貼|스티커|이모지)\s*$",
    re.IGNORECASE)

def stripSiteTitle(title):
    """去掉商店标题里的站点与分类后缀，只留包名本身。"""
    text = SITE_SUFFIX.sub("", title or "")
    return CATEGORY_SUFFIX.sub("", text).strip()

def truncateBytes(text, limit=MAX_BYTES):
    """按 UTF-8 字节数截断，避免中文/emoji 名字超出文件系统限制。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", "ignore")

def sanitize(name, fallback):
    """把网页上抓来的包名转成安全的文件名，无法使用时回落到 fallback。"""
    cleaned = INVALID_CHARS.sub("_", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = truncateBytes(cleaned).strip().rstrip(". ")
    if not cleaned or cleaned.upper() in RESERVED_NAMES:
        return fallback
    return cleaned

# ============================================================================
# HTTP 会话
# ============================================================================
TIMEOUT = (10, 60)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

def buildSession():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = buildSession()

def httpGet(url, **kwargs):
    """带默认超时的 GET。"""
    kwargs.setdefault("timeout", TIMEOUT)
    return SESSION.get(url, **kwargs)

def shortError(error):
    """把 requests 冗长的异常压成一行，避免刷屏。"""
    if isinstance(error, requests.exceptions.Timeout):
        return "连接超时"
    if isinstance(error, requests.exceptions.SSLError):
        return "SSL 证书校验失败"
    if isinstance(error, requests.exceptions.ConnectionError):
        return "无法连接到服务器"
    if isinstance(error, requests.exceptions.HTTPError):
        response = getattr(error, "response", None)
        return f"HTTP {response.status_code}" if response is not None else "HTTP 错误"
    return str(error)

# ============================================================================
# 进度条
# ============================================================================
BAR_WIDTH = 28

class Progress:
    """线程安全的进度显示。"""

    def __init__(self, total, stream=None, showBar=None):
        self.total = total
        self.completed = 0
        self.succeeded = 0
        self.skipped = 0
        self.failed = 0
        self.stream = stream or sys.stderr
        self.lock = threading.Lock()
        self.barVisible = False
        if showBar is None:
            showBar = bool(getattr(self.stream, "isatty", lambda: False)())
        self.showBar = showBar and total > 1

    def formatBar(self):
        ratio = self.completed / self.total if self.total else 1.0
        filled = int(BAR_WIDTH * ratio)
        bar = "=" * filled + "-" * (BAR_WIDTH - filled)
        parts = [f"[{bar}] {self.completed}/{self.total} ({ratio:.0%})",
                 f"成功 {self.succeeded}"]
        if self.skipped:
            parts.append(f"跳过 {self.skipped}")
        if self.failed:
            parts.append(f"失败 {self.failed}")
        return "  ".join(parts)

    def clearBar(self):
        if self.barVisible:
            self.stream.write("\r\033[K")
            self.barVisible = False

    def drawBar(self):
        if self.showBar:
            self.stream.write("\r\033[K" + self.formatBar())
            self.stream.flush()
            self.barVisible = True

    def log(self, message):
        with self.lock:
            self.clearBar()
            print(message, flush=True)
            self.drawBar()

    def advance(self, status):
        with self.lock:
            self.completed += 1
            if status == "ok":
                self.succeeded += 1
            elif status == "skip":
                self.skipped += 1
            else:
                self.failed += 1
            self.drawBar()

    def close(self):
        with self.lock:
            if self.barVisible:
                self.stream.write("\r\033[K" + self.formatBar() + "\n")
                self.stream.flush()
                self.barVisible = False

class PlainReporter:
    """不带进度条的输出，用于单个链接的场景。"""

    def log(self, message):
        print(message, flush=True)

    def advance(self, status):
        pass

    def close(self):
        pass

# ============================================================================
# 作者页处理
# ============================================================================
def getStickerUrls(url):
    response = httpGet(url)
    soup = BeautifulSoup(response.content, "html.parser")
    return [f"https://store.line.me{link['href']}"
            for link in soup.find_all('a', href=True)
            if '/stickershop/product/' in link['href']]

def processAuthorUrl(authorUrl):
    i = 1
    allStickerUrls = []
    while True:
        pageUrl = f"{authorUrl}?page={i}"
        print(f"正在检查页面: {pageUrl}")
        stickerUrls = getStickerUrls(pageUrl)
        if stickerUrls:
            allStickerUrls.extend(stickerUrls)
            i += 1
        else:
            break
    return allStickerUrls

# ============================================================================
# 贴图包下载
# ============================================================================
EMOJI_PATTERN = re.compile(r"https://store\.line\.me/emojishop/product/([a-zA-Z0-9]{23,25})")
STICKER_PATTERN = re.compile(r"https://store\.line\.me/stickershop/product/(\d{6,9})")
PRODUCT_PATTERN = re.compile(r"(https?://store\.line\.me/(?:sticker|emoji)shop/product/[^/?#]+)")
KEY_PATTERN = re.compile(r"^(key|\d+_key)(@\d+x)?$", re.IGNORECASE)

def toEnglishUrl(url):
    """把任意语言的商店链接改写成英文页链接，顺带去掉 query。"""
    match = PRODUCT_PATTERN.match(url)
    return f"{match.group(1)}/en" if match else url

def getPackName(url, fallback, reporter=None):
    """抓取包名并净化；抓不到时回落到包 ID。"""
    reporter = reporter or PlainReporter()
    try:
        response = httpGet(toEnglishUrl(url))
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        reporter.log(f"获取表情包名字失败({shortError(e)})，改用 ID: {fallback}")
        return fallback
    soup = BeautifulSoup(response.text, "html.parser")
    titleTag = soup.find("p", class_="mdCMN38Item01Ttl")
    if titleTag:
        return sanitize(titleTag.get_text(), fallback)
    ogTitle = soup.find("meta", property="og:title")
    if ogTitle and ogTitle.get("content"):
        return sanitize(stripSiteTitle(ogTitle["content"]), fallback)
    if soup.title:
        return sanitize(stripSiteTitle(soup.title.get_text()), fallback)
    reporter.log(f"未能从页面解析包名，改用 ID: {fallback}")
    return fallback

def replaceWithRetry(src, dst, attempts=20):
    """os.replace 的重试版。Windows 上刚落地的新文件常被杀毒软件独占打开扫描。"""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(min(0.3 * (attempt + 1), 1.0))

def isKeyFile(filename):
    return KEY_PATTERN.match(os.path.splitext(filename)[0]) is not None

def safeExtract(zipRef, destDir):
    """解压前校验成员路径，拒绝 zip slip（../）与绝对路径逃逸。"""
    destRoot = os.path.realpath(destDir)
    for member in zipRef.infolist():
        filename = member.filename
        if os.path.isabs(filename):
            raise ValueError(f"压缩包内存在绝对路径: {filename}")
        target = os.path.realpath(os.path.join(destRoot, filename))
        try:
            common = os.path.commonpath([destRoot, target])
        except ValueError:
            common = None
        if common != destRoot:
            raise ValueError(f"压缩包内存在非法路径: {filename}")
    zipRef.extractall(destDir)

def removeKeyFiles(zipPath, reporter=None):
    """删除包里的 key 缩略图后原地覆盖。"""
    reporter = reporter or PlainReporter()
    targetPath = os.path.abspath(zipPath)
    handle, cleanedPath = tempfile.mkstemp(
        prefix=".cleaning-", suffix=".zip", dir=os.path.dirname(targetPath)
    )
    os.close(handle)
    try:
        with tempfile.TemporaryDirectory() as tempDir:
            with zipfile.ZipFile(targetPath, "r") as zipRef:
                safeExtract(zipRef, tempDir)

            with zipfile.ZipFile(cleanedPath, "w", zipfile.ZIP_DEFLATED) as newZipRef:
                for root, _, files in os.walk(tempDir):
                    for fileName in files:
                        if isKeyFile(fileName):
                            continue
                        filePath = os.path.join(root, fileName)
                        newZipRef.write(filePath, os.path.relpath(filePath, tempDir))
        replaceWithRetry(cleanedPath, targetPath)
        reporter.log(f"已清理并保存到原文件: {targetPath}")
        return True
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        reporter.log(f"清理 key 缩略图失败（原始文件已保留）: {e}")
        return False
    finally:
        if os.path.exists(cleanedPath):
            os.remove(cleanedPath)

def downloadFile(url, filePath, reporter=None):
    """下载到 .part 临时文件，校验是 zip 后才落到最终文件名。"""
    reporter = reporter or PlainReporter()
    partPath = f"{filePath}.part"
    try:
        response = httpGet(url, stream=True)
        response.raise_for_status()
        with open(partPath, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                f.write(chunk)
        if not zipfile.is_zipfile(partPath):
            raise ValueError("服务器返回的不是有效的 zip 文件")
        replaceWithRetry(partPath, filePath)
        reporter.log(f"下载成功: {filePath}")
        return True
    except (requests.exceptions.RequestException, ValueError, OSError) as e:
        reporter.log(f"下载失败: {shortError(e)}")
        return False
    finally:
        if os.path.exists(partPath):
            os.remove(partPath)

_reservedPaths = set()
_reserveLock = threading.Lock()

def resolveZipPath(outputDir, packName, packId):
    """同名的包不互相覆盖：被别的包占用时在名字后面接上包 ID。"""
    plainPath = os.path.join(outputDir, f"{packName}.zip")
    suffixPath = os.path.join(outputDir, f"{packName}_{packId}.zip")
    fileName = f"{packName}.zip"
    with _reserveLock:
        owner = None
        for recordedId, recordedName in loadIndex(outputDir).items():
            if recordedName == fileName:
                owner = recordedId
                break
        occupied = (os.path.exists(plainPath)
                    and owner is not None
                    and owner != str(packId))
        if occupied or plainPath in _reservedPaths:
            _reservedPaths.add(suffixPath)
            return suffixPath
        _reservedPaths.add(plainPath)
        return plainPath

INDEX_NAME = ".downloaded.json"
_indexLock = threading.Lock()

def cleanStaleTempFiles(outputDir):
    """清掉上次被强制中断时留下的临时文件。"""
    patterns = (".cleaning-*.zip", "*.zip.part", INDEX_NAME + ".tmp")
    removed = 0
    for pattern in patterns:
        for path in glob.glob(os.path.join(glob.escape(outputDir), pattern)):
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed

def loadIndex(outputDir):
    """读取下载记录：包 ID -> 文件名。"""
    path = os.path.join(outputDir, INDEX_NAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def updateIndex(outputDir, mutate):
    """按 mutate 修改账本并落盘。"""
    with _indexLock:
        index = loadIndex(outputDir)
        mutate(index)
        tmpPath = os.path.join(outputDir, INDEX_NAME + ".tmp")
        try:
            with open(tmpPath, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=1)
            replaceWithRetry(tmpPath, os.path.join(outputDir, INDEX_NAME))
        except OSError:
            if os.path.exists(tmpPath):
                try:
                    os.remove(tmpPath)
                except OSError:
                    pass

def recordDownload(outputDir, packId, zipPath):
    """把包记进账本。"""
    updateIndex(outputDir,
                lambda index: index.update({str(packId): os.path.basename(zipPath)}))

def forgetDownload(outputDir, packId):
    """从账本里划掉一个包（下载失败时用）。"""
    updateIndex(outputDir, lambda index: index.pop(str(packId), None))

def findExistingPack(outputDir, packId):
    """按包 ID 查出已下载且文件仍在的 zip，找不到返回 None。"""
    fileName = loadIndex(outputDir).get(str(packId))
    if not fileName:
        return None
    path = os.path.join(outputDir, fileName)
    return path if os.path.exists(path) else None

def processUrl(url, outputDir=".", reporter=None, overwrite=False):
    """下载单个贴图包或 emoji 包。返回 "ok" / "skip" / "fail"。"""
    reporter = reporter or PlainReporter()
    emojiMatch = EMOJI_PATTERN.search(url)
    stickerMatch = STICKER_PATTERN.search(url)
    if emojiMatch:
        packId = emojiMatch.group(1)
        base = f"https://stickershop.line-scdn.net/sticonshop/v1/sticon/{packId}/iphone"
        candidates = [f"{base}/package.zip", f"{base}/package_animation.zip"]
    elif stickerMatch:
        packId = stickerMatch.group(1)
        base = f"https://stickershop.line-scdn.net/stickershop/v1/product/{packId}/iphone"
        candidates = [f"{base}/stickers@2x.zip", f"{base}/stickerpack@2x.zip"]
    else:
        reporter.log(f"URL格式错误: {url}")
        return "fail"
    existing = findExistingPack(outputDir, packId)
    if existing and not overwrite:
        reporter.log(f"已存在，跳过: {os.path.basename(existing)}")
        return "skip"
    if existing:
        zipPath = existing
        packName = os.path.splitext(os.path.basename(existing))[0]
    else:
        packName = getPackName(url, packId, reporter)
        zipPath = resolveZipPath(outputDir, packName, packId)
        recordDownload(outputDir, packId, zipPath)
    for candidate in candidates:
        if downloadFile(candidate, zipPath, reporter):
            removeKeyFiles(zipPath, reporter)
            return "ok"
    if not existing:
        forgetDownload(outputDir, packId)
    reporter.log(f"下载 {packName} 失败")
    return "fail"

# ============================================================================
# CLI
# ============================================================================
DEFAULT_JOBS = 4
MAX_JOBS = 16

def expandUrls(urls, reporter):
    """把作者页展开成一个个贴图包链接，其他链接原样保留。"""
    expanded = []
    for url in urls:
        if '/author/' not in url:
            expanded.append(url)
            continue
        authorUrl = url.split('?page=')[0]
        try:
            stickerUrls = processAuthorUrl(authorUrl)
        except requests.exceptions.RequestException as e:
            reporter.log(f"读取作者页 {authorUrl} 失败: {shortError(e)}")
            continue
        if not stickerUrls:
            reporter.log(f"在 {authorUrl} 中没有找到表情包链接。")
            continue
        reporter.log(f"作者页 {authorUrl} 找到 {len(stickerUrls)} 个表情包")
        expanded.extend(stickerUrls)
    return expanded

def runOne(url, outputDir, reporter, overwrite):
    """下载一个包，返回状态字符串；异常也收敛成 fail，避免拖垮整批。"""
    try:
        return processUrl(url, outputDir, reporter, overwrite)
    except requests.exceptions.RequestException as e:
        reporter.log(f"处理 {url} 失败: {shortError(e)}")
        return "fail"
    except OSError as e:
        reporter.log(f"处理 {url} 失败: {e}")
        return "fail"

def runAll(urls, outputDir, jobs, overwrite):
    """按并发数下载全部链接，返回 (成功, 跳过, 失败)。"""
    reporter = Progress(len(urls)) if len(urls) > 1 else PlainReporter()
    counts = {"ok": 0, "skip": 0, "fail": 0}
    try:
        if jobs > 1 and len(urls) > 1:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = [pool.submit(runOne, url, outputDir, reporter, overwrite)
                           for url in urls]
                for future in as_completed(futures):
                    status = future.result()
                    counts[status] += 1
                    reporter.advance(status)
        else:
            for url in urls:
                status = runOne(url, outputDir, reporter, overwrite)
                counts[status] += 1
                reporter.advance(status)
    finally:
        reporter.close()
    return counts["ok"], counts["skip"], counts["fail"]

def buildParser():
    parser = argparse.ArgumentParser(
        prog="line-dl",
        description="LINE 贴图包和 emoji 下载器",
        epilog="示例: python line_dl_single.py https://store.line.me/stickershop/product/1419581/zh-Hant",
    )
    parser.add_argument("urls", nargs="*", help="贴图包 / emoji / 作者页链接，可以给多个")
    parser.add_argument("-o", "--output", default="output",
                        help="输出目录，默认 output；用 -o . 下载到当前目录")
    parser.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS,
                        help=f"并发下载数，默认 {DEFAULT_JOBS}；用 -j 1 改回逐个下载")
    parser.add_argument("--overwrite", action="store_true",
                        help="重新下载已存在的包，默认跳过")
    return parser

def main(argv=None):
    parser = buildParser()
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs 至少为 1")
    jobs = min(args.jobs, MAX_JOBS)
    urls = list(args.urls)

    if not urls:
        try:
            entered = input("请输入贴图包 / emoji / 作者页网址: ").strip()
        except EOFError:
            entered = ""
        if entered:
            urls.append(entered)
    if not urls:
        parser.error("没有可下载的链接")
    outputDir = os.path.abspath(args.output)
    try:
        os.makedirs(outputDir, exist_ok=True)
    except OSError as e:
        parser.error(f"无法创建输出目录 {outputDir}: {e}")
    print(f"输出目录: {outputDir}")
    stale = cleanStaleTempFiles(outputDir)
    if stale:
        print(f"已清理上次中断残留的临时文件 {stale} 个")
    urls = expandUrls(urls, PlainReporter())
    if not urls:
        print("没有可下载的表情包")
        return 1
    if jobs > 1 and len(urls) > 1:
        print(f"共 {len(urls)} 个表情包，并发 {jobs} 个下载")
    succeeded, skipped, failed = runAll(urls, outputDir, jobs, args.overwrite)
    summary = f"完成: 成功 {succeeded}"
    if skipped:
        summary += f"，跳过 {skipped}"
    if failed:
        summary += f"，失败 {failed}"
    print(summary)
    return 1 if failed else 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)