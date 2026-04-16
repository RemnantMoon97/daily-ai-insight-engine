# 雪球数据源问题记录

## 问题一：用户搜索接口不全

- **现象**：`智能纪元AGI`、`AGENT橘`、`烟雨与萤火虫` 三个账户通过 `/query/v1/search/user.json` 搜索返回 0 结果，仅 `雪球号直通车` 可搜到（id=1776261263）
- **原因**：可能这些用户在雪球上昵称不同、已更名、或账号不存在
- **已处理**：`_find_user_id()` 已改用正确的用户搜索 API（原先错误地使用了 `suggest_stock.json` 搜索股票）
- **待解决**：需要用户确认这 3 个账户的准确雪球昵称，或在 config.py 中直接填写 `user_id`

## 问题二：Timeline 接口被 WAF 拦截

- **现象**：`/statuses/original/show.json` 接口返回阿里云 WAF 拦截页面（HTML），而非 JSON 数据
- **原因**：该接口受 Aliyun WAF 保护，需要浏览器环境执行 JavaScript 生成验证 cookie，`requests` 库无法绕过
- **已处理**：代码中已添加 WAF 检测逻辑，被拦截时输出明确提示而非报错
- **待解决**：若需采集雪球用户动态，需引入浏览器自动化方案（如 Selenium/Playwright）

## 当前可用接口

| 接口 | 状态 | 用途 |
|------|------|------|
| `/query/v1/search/user.json` | 可用 | 通过昵称搜索用户 ID |
| `/query/v1/suggest_stock.json` | 可用 | 搜索股票（非用户） |
| `/statuses/original/show.json` | WAF 拦截 | 获取用户动态 |
| `/statuses/user_timeline.json` | WAF 拦截 | 获取用户时间线 |
| `/query/v1/search/status.json` | WAF 拦截 | 搜索动态内容 |

## 可选解决方案

1. **Selenium/Playwright 方案**：通过浏览器自动化绕过 WAF，可完整获取用户动态，但增加依赖和运行开销
2. **手动配置 user_id**：在 config.py 的 XUEQIU_ACCOUNTS 中直接填写 user_id，跳过搜索步骤，但仍受 WAF 限制无法获取动态
3. **暂时搁置雪球源**：当前 X/Twitter（Nitter RSS）8 个账户运行正常（104 条/次），可满足英文社交媒体数据需求
