"""命令行工具。
  python -m app.cli reset-admin [--username admin] [--password 新密码]
  python -m app.cli backup | list-backups | restore <备份文件>（恢复前须停止应用）
不指定密码时随机生成，写入 data/admin_initial_password.txt（权限 600）并打印；下次登录须修改密码。"""
import argparse

from . import admin_auth, db


def main():
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset-admin", help="重置管理员密码（并使其所有会话失效）")
    r.add_argument("--username", default="admin")
    r.add_argument("--password", default=None)
    b = sub.add_parser("backup", help="立即备份数据库到 PH_BACKUP_DIR")
    rs = sub.add_parser("restore", help="从备份恢复（须先停止应用）")
    rs.add_argument("file")
    sub.add_parser("list-backups", help="列出备份")
    mc = sub.add_parser("m1-reclean", help="M1 存量条目正文/摘要原地清洗（去导航、元数据字段、竖排单字）")
    mc.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "restore":
        from . import backup
        print(backup.restore(a.file))
        return
    db.conn()
    if a.cmd == "reset-admin":
        pw = admin_auth.reset_password(a.username, a.password)
        print(f"已重置管理员 {a.username} 的密码。{'新密码：' + pw if not a.password else ''}")
        print(f"已写入 {admin_auth.INIT_FILE}（权限 600）；下次登录须修改密码。")
    elif a.cmd == "backup":
        from . import backup
        print(backup.backup_now("命令行"))
    elif a.cmd == "m1-reclean":
        from .m1.clean import reclean_all
        print(reclean_all(a.dry_run))
    elif a.cmd == "list-backups":
        from . import backup
        for f in backup.listing()["files"]:
            print(f["name"], f["size"])


if __name__ == "__main__":
    main()
