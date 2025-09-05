# wecom.py
# -*- coding: utf-8 -*-

from pathlib import Path
from dotenv import load_dotenv

# 同目录读取 .env（可选，但有它更稳）
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

import argparse
import json
import sys

from wecom_api import WeComAPI   # 确保 wecom_api.py 与本文件同目录

# 下面是你的命令实现……
def cmd_token(_):
    api = WeComAPI()
    print(api.access_token())

def cmd_kf_text(args):
    api = WeComAPI()
    resp = api.kf_send_text(args.user, args.text)
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    if resp.get("errcode") not in (0, None):
        sys.exit(1)

def cmd_kf_link(args):
    api = WeComAPI()
    url = api.kf_add_contact_url(args.user, scene=args.scene)
    if not url:
        print("failed to get kf add_contact url")
        sys.exit(1)
    print(url)

def cmd_welcome_add(args):
    api = WeComAPI()
    payload = {}
    if args.text:
        payload["text"] = {"content": args.text}
    if args.link_title and args.link_url:
        payload["link"] = {
            "title": args.link_title,
            "url": args.link_url,
        }
        if args.link_desc:
            payload["link"]["desc"] = args.link_desc
        if args.link_pic:
            payload["link"]["picurl"] = args.link_pic
    tpl_id = api.create_group_welcome_template(
        text=args.text,
        link=payload.get("link"),
        miniprogram=None,
    )
    print(tpl_id)

def cmd_welcome_send(args):
    api = WeComAPI()
    resp = api.send_group_welcome(chat_id=args.chat, external_userid=args.user, template_id=args.tpl)
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    if resp.get("errcode") not in (0, None):
        sys.exit(1)

def cmd_welcome_list(args):
    api = WeComAPI()
    resp = api.list_group_welcome_templates(offset=args.offset, limit=args.limit)
    print(json.dumps(resp, ensure_ascii=False, indent=2))

def cmd_welcome_del(args):
    api = WeComAPI()
    resp = api.delete_group_welcome_template(template_id=args.tpl)
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    if resp.get("errcode") not in (0, None):
        sys.exit(1)

def main():
    p = argparse.ArgumentParser(description="WeCom helper CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("token", help="print access_token")
    s.set_defaults(func=cmd_token)

    s = sub.add_parser("kf-text", help="KF 私聊发文本")
    s.add_argument("--user", required=True, help="external_userid")
    s.add_argument("--text", required=True, help="message text")
    s.set_defaults(func=cmd_kf_text)

    s = sub.add_parser("kf-link", help="生成 KF 会话链接")
    s.add_argument("--user", required=True, help="external_userid")
    s.add_argument("--scene", default="wecom_pass2u", help="scene tag")
    s.set_defaults(func=cmd_kf_link)

    s = sub.add_parser("welcome-add", help="新增群欢迎语模板（固定文案）")
    s.add_argument("--text", help="文本内容")
    s.add_argument("--link-title", help="链接标题")
    s.add_argument("--link-url", help="链接 URL")
    s.add_argument("--link-desc", help="链接描述")
    s.add_argument("--link-pic", help="链接封面图 URL（可选）")
    s.set_defaults(func=cmd_welcome_add)

    s = sub.add_parser("welcome-send", help="发送群欢迎语（固定模板）")
    s.add_argument("--chat", required=True, help="chat_id")
    s.add_argument("--user", required=True, help="external_userid")
    s.add_argument("--tpl", help="template_id（不传则用环境变量 WECOM_GROUP_WELCOME_TEMPLATE_ID）")
    s.set_defaults(func=cmd_welcome_send)

    s = sub.add_parser("welcome-list", help="列出欢迎语模板")
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--limit", type=int, default=100)
    s.set_defaults(func=cmd_welcome_list)

    s = sub.add_parser("welcome-del", help="删除欢迎语模板")
    s.add_argument("--tpl", required=True, help="template_id")
    s.set_defaults(func=cmd_welcome_del)

    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()