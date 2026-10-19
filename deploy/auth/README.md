在此目录放置 `basic_auth.caddy`（不入库），内容形如：

    basic_auth {
        puhui <bcrypt 哈希，用 caddy hash-password 生成>
    }

目录为空时全站不加口令（仅限内网/测试）。
