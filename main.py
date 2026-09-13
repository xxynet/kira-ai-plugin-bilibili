import re
import httpx
from datetime import datetime

from bilibili_api import video, comment, search, homepage, Credential, exceptions as bili_e
from bilibili_api.comment import CommentResourceType
from bilibili_api.utils import network

from core.plugin import BasePlugin, logger, register
from core.agent.tool import ToolResult
from core.chat.message_elements import File
from core.utils.path_utils import get_data_path


def format_time(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


async def _search_videos_with_count(keyword, count):
    result = await search.search_by_type(
        keyword=keyword,
        search_type=search.SearchObjectType.VIDEO,  # 指定搜索视频类型
        page_size=count  # 指定返回几个视频
    )
    result = result["result"]

    videos = []
    for item in result:
        videos.append({
            "bvid": item.get("bvid"),
            "title": re.sub(r'<.*?>', '', item.get("title") or ''),
            "author": item.get("author"),
            "description": item.get("description"),
            "views": item.get("play"),
            "likes": item.get("like"),
            "duration": item.get("duration"),
            "pubdate": datetime.fromtimestamp(item.get("pubdate", 0)).strftime("%Y-%m-%d %H:%M:%S"),
            # "cover_url": "https:" + item.get("pic") if item.get("pic") else None,
            "tags": item.get("tag"),
            "url": f"https://www.bilibili.com/video/{item.get('bvid')}",
        })
    return str(videos)


def clean_feed_items(feed_json, vid_count):
    items = feed_json.get("item", [])
    results = []

    count = 0

    for v in items:
        results.append({
            "id": v.get("id"),
            "bvid": v.get("bvid"),
            "title": v.get("title"),
            # "cover": v.get("pic"),
            # "url": v.get("uri"),
            "duration": v.get("duration"),
            "pubdate": format_time(v.get("pubdate", 0)),
            "uploader": {
                "uid": v.get("owner", {}).get("mid"),
                "name": v.get("owner", {}).get("name"),
                # "face": v.get("owner", {}).get("face"),
            },
            "stat": {
                "view": v.get("stat", {}).get("view"),
                "like": v.get("stat", {}).get("like"),
                "danmaku": v.get("stat", {}).get("danmaku"),
            },
            "recommend_reason": v.get("rcmd_reason", {}).get("content") or "",
        })

        count += 1
        if count == vid_count:
            break

    return results


class BiliBiliPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self._credential = None
        self._network_client = None

    async def initialize(self):
        network.select_client("aiohttp")
        self._network_client = network.get_client()
        session = self._network_client.get_wrapped_session()
        session.headers["Accept-Encoding"] = "gzip, deflate"
        self._credential = Credential(
            sessdata=self.plugin_cfg.get("sessdata", ""),
            bili_jct=self.plugin_cfg.get("bili_jct", ""),
            buvid3=self.plugin_cfg.get("buvid3", ""),
            dedeuserid=self.plugin_cfg.get("dedeuserid", ""),
            ac_time_value=self.plugin_cfg.get("ac_time_value", ""),
        )

    async def terminate(self):
        network_client = self._network_client
        self._network_client = None
        if network_client:
            await network_client.close()

    @staticmethod
    async def _resolve_b23(url: str) -> str:
        if not url.startswith("https://b23.tv/"):
            return url

        async with httpx.AsyncClient(follow_redirects=False) as client:
            current = url
            while True:
                resp = await client.head(current)
                location = resp.headers.get("location")
                if not location:
                    return current
                current = location

    async def _video_handle(self, original_url: str):
        link = await self._resolve_b23(original_url)
        bvid = re.findall(r"BV[a-zA-Z0-9]{10}", link)[0]
        v = video.Video(bvid=bvid, credential=self._credential)
        info = await v.get_info()

        video_bvid = info["bvid"]
        title = info["title"]
        desc = info["desc"]
        tname = info["tname"]
        tname_v2 = info.get("tname_v2")

        pubdate = datetime.fromtimestamp(info["pubdate"]).strftime("%Y-%m-%d %H:%M:%S")
        up_info = info["owner"]
        stat = info["stat"]

        video_info_str = (
            f"以下是视频相关信息：bvid: {video_bvid}, title: {title}, description: {desc}, "
            f"分区：{tname} - {tname_v2}, 发布时间：{pubdate}, 作者信息：{up_info}, 互动数据：{stat}"
        )
        return video_info_str, v, info

    @register.tool(
        name="bilibili_video_info",
        description="通过B站视频链接获取视频基本信息（www.bilibili.com/video/ 或 b23.tv/）",
        params={
            "type": "object",
            "properties": {
                "original_url": {"type": "string", "description": "B站视频url"}
            },
            "required": ["original_url"]
        }
    )
    async def bilibili_video_info(self, *_, original_url: str):
        try:
            info_str, _, _ = await self._video_handle(original_url)
            return info_str
        except Exception as bili_info_e:
            return str(bili_info_e)

    @register.tool(
        name="like_bilibili_video",
        description="给B站视频点赞",
        params={
            "type": "object",
            "properties": {
                "original_url": {"type": "string", "description": "B站视频url"}
            },
            "required": ["original_url"]
        }
    )
    async def _like_bilibili_video(self, *_, original_url: str):
        try:
            info_str, v, _ = await self._video_handle(original_url)
            await v.like()
        except bili_e.ResponseCodeException as e:
            return f"点赞失败！{str(e)}"
        return f"点赞成功！"

    @register.tool(
        name="comment_bilibili_video",
        description="在B站视频下发表评论，评论前先调用 bilibili_video_info 工具获取视频信息",
        params={
            "type": "object",
            "properties": {
                "original_url": {"type": "string", "description": "B站视频url"},
                "comment_content": {"type": "string", "description": "评论内容"},
            },
            "required": ["original_url", "comment_content"]
        }
    )
    async def comment_bilibili_video(self, *_, original_url: str, comment_content: str):
        try:
            info_str, _, info = await self._video_handle(original_url)
        except Exception as bili_info_e:
            return str(bili_info_e)

        result = await comment.send_comment(
            text=comment_content,
            oid=info["aid"],
            type_=CommentResourceType.VIDEO,
            credential=self._credential
        )
        reply_status = result.get("success_toast")
        reply_content = result.get("reply").get("content").get("message")
        return f"status: {reply_status}, reply_content: {reply_content}"

    @register.tool(
        name="bilibili_search",
        description="通过关键词搜索B站视频",
        params={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"}
            },
            "required": ["keyword"]
        }
    )
    async def bilibili_search(self, *_, keyword: str):
        try:
            res = await _search_videos_with_count(keyword, 5)
            return res
        except Exception as bili_search_e:
            return str(bili_search_e)

    @staticmethod
    def _format_subtitle_timestamp(seconds: float) -> str:
        total = int(seconds)
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    # Region codes that map onto a script code for language matching
    _LANG_REGION_TO_SCRIPT = {
        "cn": "hans", "sg": "hans",
        "tw": "hant", "hk": "hant", "mo": "hant",
    }

    @classmethod
    def _parse_lang_code(cls, code: str) -> tuple[str, str]:
        """Parse a language code into (base_language, script) for matching.

        Case-insensitive, accepts `_` or `-` separators, maps region codes
        onto script codes (zh-CN -> zh-hans) and strips the `ai-` prefix
        Bilibili uses for auto-generated subtitles.
        """
        code = (code or "").strip().lower().replace("_", "-")
        if code.startswith("ai-"):
            code = code[3:]
        parts = [p for p in code.split("-") if p]
        if not parts:
            return "", ""
        lang = parts[0]
        script = ""
        for p in parts[1:]:
            if p in ("hans", "hant"):
                script = p
            elif p in cls._LANG_REGION_TO_SCRIPT:
                script = cls._LANG_REGION_TO_SCRIPT[p]
        return lang, script

    @classmethod
    def _pick_subtitle_track(cls, tracks: list, lan: str):
        """Pick the best subtitle track for the requested language.

        Scores each track: exact code match (4), same language and script
        (3), same base language ignoring AI prefix and script (1); ties and
        total misses fall back to the first track.
        """
        req = (lan or "").strip().lower().replace("_", "-")
        req_lang, req_script = cls._parse_lang_code(lan)
        best, best_score = tracks[0], -1
        for t in tracks:
            t_lan = (t.get("lan") or "").strip().lower().replace("_", "-")
            t_lang, t_script = cls._parse_lang_code(t.get("lan") or "")
            if req and t_lan == req:
                score = 4
            elif req_lang and req_script and t_lang == req_lang and t_script == req_script:
                score = 3
            elif req_lang and t_lang == req_lang:
                score = 1
            else:
                score = 0
            if score > best_score:
                best, best_score = t, score
        return best

    @staticmethod
    def _srt_timestamp(seconds: float) -> str:
        millis = int(round(seconds * 1000))
        hours, rem = divmod(millis, 3600000)
        minutes, rem = divmod(rem, 60000)
        secs, ms = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    @classmethod
    def _build_srt(cls, entries: list[tuple[float, float, str]]) -> str:
        cues = []
        for idx, (start, end, content) in enumerate(entries, start=1):
            if end <= start:
                end = start + 2
            cues.append(
                f"{idx}\n{cls._srt_timestamp(start)} --> {cls._srt_timestamp(end)}\n{content}\n"
            )
        return "\n".join(cues)

    async def _fetch_subtitle(
        self, v: video.Video, info: dict, lan: str = "", bvid: str = ""
    ) -> ToolResult:
        cid = info.get("cid")
        if cid is None:
            return ToolResult(text="获取视频 cid 失败，无法获取字幕")

        subtitle_info = await v.get_subtitle(cid=cid)
        tracks = subtitle_info.get("subtitles") or []
        if not tracks:
            return ToolResult(text="该视频没有可用的CC字幕（AI生成字幕需要登录凭据）")

        # Match the requested language with normalization, miss falls back to the first track
        track = self._pick_subtitle_track(tracks, lan)
        url = track.get("subtitle_url") or ""
        if url.startswith("//"):
            url = "https:" + url
        if not url:
            return ToolResult(text="字幕下载地址为空")

        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            data = resp.json()

        body = data.get("body") or []
        # Strip Bilibili bcc styling tags (e.g. <i>...</i>) for clean plain text
        entries = [
            (
                float(item.get("from", 0) or 0),
                float(item.get("to", 0) or 0),
                re.sub(r"<.*?>", "", item.get("content", "")).strip(),
            )
            for item in body
            if item.get("content")
        ]
        if not entries:
            return ToolResult(text="字幕内容为空")

        label = track.get("lan_doc") or track.get("lan") or "unknown"
        text = "字幕语言：" + label + "\n" + "\n".join(
            f"[{self._format_subtitle_timestamp(start)}] {content}"
            for start, _, content in entries
        )

        # Save as a standard SRT file the user can receive through <file> tags
        save_dir = get_data_path() / "temp" / "bilibili_subtitles"
        save_dir.mkdir(parents=True, exist_ok=True)
        safe_lan = re.sub(r"[^0-9A-Za-z-]", "", track.get("lan") or "sub") or "sub"
        filename = f"{bvid or 'subtitle'}_{safe_lan}.srt"
        file_path = save_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self._build_srt(entries))

        return ToolResult(
            text=text,
            attachments=[File(file=str(file_path), name=filename)],
        )

    @register.tool(
        name="bilibili_video_subtitle",
        description="获取/下载B站视频的CC字幕，返回字幕文本并保存为SRT字幕文件，仅部分视频有字幕（AI生成字幕需要登录凭据）",
        params={
            "type": "object",
            "properties": {
                "original_url": {"type": "string", "description": "B站视频url"},
                "lan": {"type": "string", "description": "字幕语言代码，如 zh / zh-CN / zh-Hans / zh-TW / en / ai-zh，写法自动归一化，不填默认返回第一条字幕"},
            },
            "required": ["original_url"]
        }
    )
    async def bilibili_video_subtitle(self, *_, original_url: str, lan: str = ""):
        try:
            _, v, info = await self._video_handle(original_url)
            return await self._fetch_subtitle(v, info, lan, bvid=info.get("bvid", ""))
        except Exception as bili_subtitle_e:
            return ToolResult(text=str(bili_subtitle_e))

    async def _get_personalized_feed(self, count: int = 5):
        # 使用登录凭据获取个性化推荐
        result = await homepage.get_videos(credential=self._credential)
        cleaned_feed = clean_feed_items(result, count)
        return cleaned_feed

    @register.tool(
        name="bilibili_feed",
        description="获取B站首页视频",
        params={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    async def bilibili_feed(self, *_):
        try:
            feed = await self._get_personalized_feed(count=5)
            return str(feed)
        except Exception as bili_feed_e:
            return str(bili_feed_e)
