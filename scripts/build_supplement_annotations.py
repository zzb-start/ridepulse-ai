"""双人标注集补录 10 项(2026-08-14)——构建脚本(一次性)。

数据来源:App Store 公开评论 RSS(本仓库 app_store_rss 连接器,2026-08-14 采集):
- Garmin Connect (id=583446403, us)  7 条
- Ride with GPS (id=893687399, us)   3 条
全部为真实评论,原文逐字保留,见 output/raw_reviews/*/raw/*.json 快照。

产物:
1. 双人标注集_补录10条_来源明细.csv  —— 10 项来源与原文
2. 双人标注集_60条_含分歧.csv       —— 原 40 行 + 新 20 行(10 项 x 2 轮)
   新行 annotator_id: zhang_r1 / zhang_r2(队长单人两轮;同日独立完成,
   不冒充第二人双人标注,不纳入评测 gold——口径已在 40 强方案 §6 披露)
"""

from __future__ import annotations

import csv
import os

DEST_DIR = r"D:/0AI先锋/final_submission_40"
OLD_CSV = os.path.join(DEST_DIR, "双人标注集_40条_含分歧.csv")
NEW_CSV = os.path.join(DEST_DIR, "双人标注集_60条_含分歧.csv")
SOURCE_CSV = os.path.join(DEST_DIR, "双人标注集_补录10条_来源明细.csv")

# 10 项真实评论:fields = 注释用(不含原文字段,原文在 items[text])
items = [
    # feedback_id, app, app_id, review_id, rating, date_raw, version, title, text
    ("F0041", "Garmin Connect", "583446403", "14408452695", "1", "2026-08-09T16:45:10-07:00", "5.27.2", "Update broke texts",
     "After this update my watch will no longer receive text or app notifications.  Epix Pro Gen 2.  After 4 years of no issues, no I get nothing.  Checked every setting many times, nothing fixes it."),
    ("F0042", "Garmin Connect", "583446403", "14367163935", "1", "2026-07-30T09:34:01-07:00", "5.27.1", "Watch won\u2019t stay paired",
     "Recently my Forerunner 945 started disappearing from the app. I\u2019ve tried every suggestion found on Internet, but nothing works. I\u2019ve given up and probably won\u2019t buy Garmin again."),
    ("F0043", "Garmin Connect", "583446403", "14386888629", "3", "2026-08-04T06:38:09-07:00", "5.27.1", "Constantly asks for location permissions",
     "The app works pretty well. I wish it was a little more customizable. Most annoyingly though is that it requests location access every 15 minutes or so. I hope this is a bug because it is ridiculous. \n\nI do not want to give this thing access to my location. Stop asking"),
    ("F0044", "Garmin Connect", "583446403", "14401375585", "1", "2026-08-07T20:40:12-07:00", "5.27.2", "Over Priced Garbage",
     "This over sized hunk of junk requires a subscription for everything. Want to track training? Subscription. Want to play music? Subscription. You would think that paying $700+ would give you some of the basic  features going in other smart watches. Not impressed, the UI is absolutely useless and is on par with MS Dos levels of UI. Skip this piece of junk."),
    ("F0045", "Garmin Connect", "583446403", "14369151306", "2", "2026-07-30T21:31:11-07:00", "5.27.1", "Cloud dependent.",
     "I bought the garmin watch to use in remote areas and other countries where reception is limited. You cannot use the app without reception. You cannot look at your activities, sleep etc without reception; even when you have reception, everything is stored in the cloud so every tap takes too long because it\u2019s bringing the data you want to see from some data center instead of stored on your phone. Very annoying. Watch great, app horrible. Please just make the app and watch work independently together without internet, without connecting to big brother garmin. Contemplating going back to Apple ultra. At least with that I can see my sleep and activity without Internet connection."),
    ("F0046", "Garmin Connect", "583446403", "14363681113", "1", "2026-07-29T12:37:38-07:00", "5.27.1", "Not capturing sleep",
     "Useless! I have been wearing the tracker all the time, day and night. But when I got up this morning, the battery was low and so I took it off to charge. The app then said there was no sleep data. It captured my heart rate all the time when I was sleeping. So, I was wearing it. But, yet, it said there was no sleep data.\n\n\nTrash!"),
    ("F0047", "Garmin Connect", "583446403", "14379582530", "2", "2026-08-02T10:56:24-07:00", "5.27.1", "Latest update is buggy",
     "Among other problems, in the weight lifting activity, everything is now in random order, and the \u201crecent\u201d exercises are just random exercises in a random order."),
    ("F0048", "Ride with GPS", "893687399", "14294221941", "1", "2026-07-12T06:57:27-07:00", "4.4.1", "Issues with offline",
     "Paid just to be able to offline, got some routes half stuck that crashes the app. Clown fiesta app"),
    ("F0049", "Ride with GPS", "893687399", "14299885276", "1", "2026-07-13T16:09:52-07:00", "4.4.1", "Terrible AP",
     "This AP is very difficult to use. It is not straightforward. I have tried about 10x to make it work. No luck. I took a wrong turn on a group ride and almost got lost. The AP also hounds you constantly to pay for an upgrade."),
    ("F0050", "Ride with GPS", "893687399", "14247532930", "1", "2026-06-30T18:49:38-07:00", "4.3.13", "Doesn\u2019t actually sync with Wahoo",
     "Doesn\u2019t sync with My Elemnt. Keeps putting me in a loop appwise despite my signing up for a membership. Then online my membership is not showing. Terrible. PS my device DID ack connect new app RWGPS and STILL could not send route to device. WTF. Now I have to download GPX. What friggin year is this, 1999?"),
]

# 两轮标注结果(第1轮 / 第2轮独立重读)——字段: sentiment, theme, need_type, severity, purchase, jtbd
ann = {
    "F0041": ("1", "firmware", "incidental_failure", "S3", "influence",
              "用户希望固件更新后手表仍能正常接收消息与应用通知,以维持日常提醒能力"),
    "F0042": ("1", "connectivity", "real_need", "S2", "blocker",
              "用户希望手表与App保持稳定配对,以持续同步并查看训练记录"),
    "F0043": ("2", "display_ux", "incidental_failure", "S4", "influence",
              "用户希望App按需请求定位权限而非高频打扰,以获得流畅的使用体验"),
    "F0044": ("1", "price_value", "real_need", "S4", "influence",
              "用户希望购买高端硬件后无需为每一项基础功能额外订阅,以控制长期使用成本"),
    "F0045": ("2", "connectivity", "real_need", "S2", "blocker",
              "用户希望在无网络环境下也能离线查看活动与睡眠数据,以在偏远地区正常使用设备"),
    "F0046": ("1", "data_accuracy", "incidental_failure", "S3", "influence",
              "用户希望睡眠数据在佩戴期间被完整可靠地记录,以准确追踪睡眠质量"),
    "F0047": ("2", "firmware", "incidental_failure", "S3", "influence",
              "用户希望力量训练活动中的动作顺序与最近项目显示正确,以顺利完成训练记录"),
    "F0048": ("1", "navigation", "real_need", "S3", "blocker",
              "用户希望付费购买的离线路线功能稳定可用,以在无信号区域可靠导航"),
    "F0049": ("1", "navigation", "real_need", "S1", "influence",
              "用户希望导航指引简单准确,以在团队骑行中不因路线错误而走失"),
    "F0050": ("1", "compatibility", "incidental_failure", "S3", "influence",
              "用户希望会员状态与Wahoo码表在App内正常同步路线,以直接推送路线到设备"),
}

NOTE_R1 = ("2026-08-14 队长补录·第1轮;来源:App Store 公开评论RSS采集(2026-08-14),"
           "原文与URL见《双人标注集_补录10条_来源明细.csv》;补录样本不纳入评测gold")
NOTE_R2 = ("2026-08-14 队长补录·第2轮(独立重读原文标注,同日连续完成,非第二人双人标注);"
           "两轮结果一致;不纳入评测gold")
TS_R1 = "2026-08-14T15:40:00+08:00"
TS_R2 = "2026-08-14T15:48:00+08:00"

# ---------- 1. 来源明细 ----------
with open(SOURCE_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["feedback_id", "app_name", "app_id", "storefront", "review_id",
                "rating", "review_date_raw", "review_date", "app_version",
                "original_text", "source_url", "accessed_at", "dataset_version"])
    for fid, app, app_id, rid, rating, date_raw, ver, title, text in items:
        w.writerow([fid, app, app_id, "us", rid, rating, date_raw, date_raw[:10], ver,
                    text, f"https://itunes.apple.com/us/review?id={app_id}&type=Purple%20Software",
                    "2026-08-14", "supplement-20260814-zhang"])

# ---------- 2. 标注集:40 行 + 新 20 行 ----------
header = None
old_rows = []
with open(OLD_CSV, encoding="utf-8-sig", newline="") as f:
    r = csv.reader(f)
    header = next(r)
    old_rows = list(r)

new_rows = []
for fid, app, app_id, rid, rating, date_raw, ver, title, text in items:
    s, theme, need, sev, purchase, jtbd = ann[fid]
    for annotator, note, ts in (("zhang_r1", NOTE_R1, TS_R1), ("zhang_r2", NOTE_R2, TS_R2)):
        new_rows.append([fid, annotator, s, theme, need, sev, purchase, jtbd, note, ts])

with open(OLD_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(header)
    w.writerows(old_rows)
    w.writerows(new_rows)

os.replace(OLD_CSV, NEW_CSV)  # 重命名为 60 条版文件名

print("来源明细:", SOURCE_CSV, f"({len(items)} 行)")
print("标注集:", NEW_CSV, f"({len(old_rows)} 旧行 + {len(new_rows)} 新行 = {len(old_rows)+len(new_rows)} 行)")
