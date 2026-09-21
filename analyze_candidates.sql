-- analyze_candidates.sql: 筛选待分析的新闻
-- 噪声过滤规则：近 7 天 AND (非 HN 源 OR HN 分数 >= 5)
-- 幂等：只选 ai_status != 'done' 的记录

-- PostgreSQL 版本
SELECT id, title, summary, source_id, source_name, published_at
FROM news
WHERE COALESCE(published_at, fetched_at) >= NOW() - INTERVAL '7 days'
  AND ai_status IS DISTINCT FROM 'done'
  AND (
    source_id != 'hackernews'
    OR (summary ~ '\d+ 分' AND (regexp_match(summary, '(\d+) 分'))[1]::int >= 5)
  )
ORDER BY COALESCE(published_at, fetched_at) DESC;

-- SQLite 版本（本地开发用）
-- SELECT id, title, summary, source_id, source_name, published_at
-- FROM news
-- WHERE COALESCE(published_at, fetched_at) >= datetime('now', '-7 days')
--   AND (ai_status IS NULL OR ai_status != 'done')
--   AND (
--     source_id != 'hackernews'
--     OR (summary LIKE '% 分' AND CAST(
--         COALESCE(
--           SUBSTR(summary, INSTR(summary, '·') + 2),
--           '0'
--         ) AS INTEGER) >= 5
--     )
--   )
-- ORDER BY COALESCE(published_at, fetched_at) DESC;
