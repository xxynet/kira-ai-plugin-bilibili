import re
import httpx
from datetime import datetime

from bilibili_api import video, comment, search, homepage, Credential, exceptions as bili_e
from bilibili_api.comment import CommentResourceType

from core.plugin import BasePlugin, logger, register


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

    async def initialize(self):
        self._credential = Credential(
            sessdata=self.plugin_cfg.get("sessdata", ""),
            bili_jct=self.plugin_cfg.get("bili_jct", ""),
            buvid3=self.plugin_cfg.get("buvid3", ""),
            dedeuserid=self.plugin_cfg.get("dedeuserid", ""),
            ac_time_value=self.plugin_cfg.get("ac_time_value", ""),
        )

    async def terminate(self):
        pass

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
        return video_info_str, v, info["aid"]

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
            info_str, _, aid = await self._video_handle(original_url)
        except Exception as bili_info_e:
            return str(bili_info_e)

        result = await comment.send_comment(
            text=comment_content,
            oid=aid,
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
