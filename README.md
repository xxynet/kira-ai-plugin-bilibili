# kira-ai-plugin-bilibili

**B站工具** — 赋予 KiraAI 使用哔哩哔哩的能力。

## 功能

| 工具 | 描述 |
|------|------|
| `bilibili_video_info` | 通过视频链接获取视频基本信息（支持 `www.bilibili.com/video/` 和 `b23.tv/` 短链） |
| `bilibili_search` | 通过关键词搜索 B 站视频，返回前 5 条结果 |
| `bilibili_feed` | 获取 B 站首页个性化推荐视频 |
| `like_bilibili_video` | 给指定视频点赞 |
| `comment_bilibili_video` | 在指定视频下发表评论 |

## 配置

插件需要填入 B 站账号的 Cookie 信息以完成身份认证（部分功能如点赞、评论、个性化推荐需要登录）。

| 字段 | 来源 | 说明 |
|------|------|------|
| `sessdata` | Cookie | B 站身份凭证 |
| `bili_jct` | Cookie | CSRF Token |
| `buvid3` | Cookie | 设备标识 |
| `dedeuserid` | Cookie | 用户 UID |
| `ac_time_value` | LocalStorage | 活跃时间值 |

### 获取 Cookie 方法

1. 登录 [bilibili.com](https://www.bilibili.com)
2. 打开浏览器开发者工具（F12）→ Application → Cookies
3. 找到对应字段并复制值填入插件配置

## 依赖

```
bilibili-api-python
httpx
```

## 信息

- **插件 ID**: `kira-ai-plugin-bilibili`
- **版本**: 1.0.0
- **作者**: xxynet
