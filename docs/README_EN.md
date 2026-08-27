[Chinese README](../README.md) /[Telegram](https://t.me/yume_yuki)/[QQ](https://qm.qq.com/q/dCn4enLQly)

# LINE Stickers and Emoji Downloader

A Python tool to download stickers and emoji from the LINE Store, supporting static images, animated images, and batch downloads. This project is prohibited for illegal use and sale. **If you like these stickers, please support the official LINE stickers**

## Directory

- [LINE Stickers and Emoji Downloader](#line-stickers-and-emoji-downloader)
  - [Directory](#directory)
  - [Script Dependencies](#script-dependencies)
  - [How to use](#how-to-use)
    - [Optional arguments](#optional-arguments)
    - [Skipping already-downloaded packs](#skipping-already-downloaded-packs)
    - [Concurrency and progress](#concurrency-and-progress)
  - [Errors and solutions](#errors-and-solutions)
    - [1. Unable to get the sticker pack name](#1-unable-to-get-the-sticker-pack-name)
    - [2. Unable to download](#2-unable-to-download)
    - [3. Temp files are not deleted after download](#3-temp-files-are-not-deleted-after-download)
    - [4. Cleanup of thumbnail files fails (`[WinError 5]` / `[WinError 32]`)](#4-cleanup-of-thumbnail-files-fails-winerror-5--winerror-32)
    - [5. Others](#5-others)
  - [Acknowledgement](#acknowledgement)
  - [License](#license)

## Script Dependencies

> First, make sure that your computer has **python3.6** or above installed and python is included in your computer's **PATH**! Ensure your pip is the latest version, you can update your pip by running `python -m pip install --upgrade pip`.

You can run the following command to install the dependent libraries.
```bash
pip install requests beautifulsoup4
```

> `zipfile`, `tempfile` and friends ship with python as standard library modules — do not install them with pip.

## How to use

Run `line_dl_single.py` from the project root:

```bash
# Single pack
python line_dl_single.py <url>

# Multiple packs
python line_dl_single.py <url1> <url2> <url3>

# Creator page (automatically paginate through all works)
python line_dl_single.py <url>

# Interactive input (run directly and paste the link)
python line_dl_single.py
```

### Optional arguments

| Argument | Description |
|----------|-------------|
| `-o DIR` / `--output DIR` | Output directory, defaults to `output`. Use `-o .` to download into the current directory. |
| `-j N` / `--jobs N` | Number of concurrent downloads, defaults to `4`, capped at `16`. Use `-j 1` for sequential downloads. |
| `--overwrite` | Re-download packs that were already downloaded (skipped by default). |
| `-h` / `--help` | Show the full help text. |

### Skipping already-downloaded packs

The script keeps a `.downloaded.json` file in the output directory mapping "pack ID → filename". Packs that were already downloaded are skipped on subsequent runs — **no re-download and no wasted requests** — so if you interrupt a creator-page download with `Ctrl+C`, simply re-running it picks up where it left off.

- If you delete one of the zips by hand, only that one gets re-fetched.
- Pass `--overwrite` to force a re-download; it overwrites the original file rather than creating a copy.
- Deleting `.downloaded.json` makes every pack look un-downloaded again.

### Concurrency and progress

Multiple packs are downloaded 4-at-a-time by default, with a progress bar:

```
[==============--------------] 3/6 (50%)  成功 2  跳过 1
```

For large jobs (a creator with 150+ packs) the default is fine, and `-j 8` works well too — but avoid going much higher, both to stay under LINE's rate limits and to be polite. The progress bar is suppressed when output is redirected to a file, leaving only the log lines.

Examples:

```bash
python line_dl_single.py <url>
python line_dl_single.py <url> -o ./stickers
python line_dl_single.py <url1> <url2> -j 8
```

## Errors and solutions

### 1. Unable to get the sticker pack name
Since `v0.3.0`, when the name cannot be scraped the pack ID is used as the filename instead (e.g. `1419581.zip`), so packs no longer share a single `unknown_emoji_name` and overwrite each other. If you want the proper names, please check your network environment and whether your network IP is outside the region where LINE provides services.

### 2. Unable to download
Since `v0.3.0`, downloads are written to a `.part` file and verified to be a real zip before being renamed, so a failure no longer leaves a corrupted zip or an empty folder behind. If it still fails, please raise an issue and include the full error output.

### 3. Temp files are not deleted after download
Since `v0.3.0` the temporary file used for cleaning is created next to the target file and removed in a `finally` block, so it should not be left behind.
- If you use termux on your mobile phone and try to download in the storage directory, then you have stacked the buffs. The termux on some mobile phones intercepts the deletion of files in the storage directory and its subdirectories.
- If you are using another device or the error does not occur in the storage directory, please check if you have permissions in the directory of this folder.

### 4. Cleanup of thumbnail files fails (`[WinError 5]` / `[WinError 32]`)

If you see a line like
```
清理 key 缩略图失败（原始文件已保留）: [WinError 5] 拒绝访问。...
```

This is **not a download failure**. The sticker pack's zip has already been downloaded and saved intact; the script merely failed to repack it after removing the `key` thumbnails (`key.png` or `001_key.png`) — `os.replace` was denied by the system. The archive is still fully usable, it just keeps some extra thumbnails inside.

- It happens intermittently on Windows and is suspected to relate to freshly-written files being held open (antivirus scanning, OneDrive sync, indexing service, etc.). The exact cause has not been identified.
- If you can reproduce it consistently, please open an issue and include:
  - the full error output,
  - which kind of pack it happened on (sticker / emoji),
  - your Windows version and any antivirus / sync software in use.
  A reproducible pattern will help fix the root cause.

### 5. Others
If you encounter other problems besides the above, please raise an issue and reproduce the problem record submitted. Thank you for your support of this project.

## Acknowledgement

Thanks to the following friends and contributors: (in no particular order)  
[@kaixinol](https://github.com/kaixinol) | [@ZGQ Inc.](https://github.com/ZGQ-inc) | [@CPuddingOwO](https://github.com/CPuddingOwO) 

## License

```
MIT License

Copyright (c) 2024 元亓

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
