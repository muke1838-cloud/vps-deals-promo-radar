ILANG
[TYPE:agents][PROJECT:vps-deals][LANG:zh]

::STATE{@PROJECT, kind:优惠细分垂直站, brand:vps-deals, niche:vps-hosting, runtime:static}
::STATE{@STACK, scraper:scraper.py, builder:build.py, config:.ilang/site.ilang, host:Cloudflare Pages, ci:GitHub Actions}

::OBJECTIVE{keep_the_pipeline_honest}
  这是一个会自己更新的 VPS 优惠静态站。运行时零推理、零 API 密钥、纯 Python。
  站点规则只活在 .ilang/site.ilang。改厂商清单后重跑 scraper 和 build，站必须跟着变。

::MODULE{ALLOWED}
  抓 site.ilang 里列出的公开优惠页、sitemap、feed
  只提取页面上已经写明的 title / price / currency / offer_url / valid_until
  用 build.py 生成 site/ 静态页、canonical、sitemap、JSON-LD
  用 GitHub Actions 每 6 小时 scrape + build + commit
  联盟链接只能填正规联盟的公开跟踪 URL，空着就用厂商裸链

::MODULE{DATA}
  真源是各厂商官方页面，不是第三方比价站，不是模型记忆
  offers.json 每次覆盖，保留 fetched_at 和 source_url
  抓不到价格就不写 price，也不写进 Offer 结构化数据

::BOUNDARY{never:编优惠 编价格 编佣金 编有效期 绕 robots 或反爬 运行时调用收费推理|scope:permanent}

::MODULE{DO_NOT}
  不要在 scraper.py / build.py 里再写一份厂商清单
  不要把搜索摘要或旧对话里的价格填进数据集
  不要把 pages.dev 年份当成自定义域名资产
  不要申请联盟审核前假装已经有佣金数字
