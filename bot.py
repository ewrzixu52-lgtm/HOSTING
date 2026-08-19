#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import time
import random
import string
import asyncio
import base64
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToDict
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
# Remove this import completely
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8879538717:AAFyLMHlZ-pS1q23-rWx9_Hb7WLHq560G78")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "7892255798").split(",")]
MAX_CHANNELS = 5
REFERRALS_NEEDED = 5
POINTS_PER_REFERRAL = 10
POINTS_NEEDED_FOR_FOLLOW = 50
DEVELOPER_USERNAME = "@TSIW01"

# ==================== PROTOBUF SETUP ====================
# Remove this entire block

_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x0c\x66ollow.proto\x12\x05proto\" \n\x0b\x43SFollowReq\x12\x11\n\ttarget_id\x18\x01 \x01(\x04\"\xbc\x01\n\x0b\x43SFollowRes\x12%\n\x04info\x18\x01 \x01(\x0b\x32\x17.proto.AccountInfoBasic\x12\x1c\n\x14remaining_play_count\x18\x02 \x01(\r\x12!\n\x19remaining_follow_capacity\x18\x03 \x01(\r\x12\x32\n\rcreator_stats\x18\x04 \x01(\x0b\x32\x1b.proto.WorkshopCreatorStats\x12\x11\n\tfail_info\x18\x05 \x01(\t\"\xe2\x01\n\x0e\x41\x63\x63ountPrefers\x12\x15\n\rhide_my_lobby\x18\x01 \x01(\x08\x12\x1c\n\x14pregame_show_choices\x18\x02 \x03(\r\x12\x1f\n\x17\x62r_pregame_show_choices\x18\x03 \x03(\r\x12\x1a\n\x12hide_personal_info\x18\x04 \x01(\x08\x12\x1f\n\x17\x64isable_friend_spectate\x18\x05 \x01(\x08\x12\x17\n\x0fhide_occupation\x18\x06 \x01(\x08\x12$\n\x1c\x63s_peak_pregame_show_choices\x18\x07 \x03(\r\"\x84\x01\n\x10\x45xternalIconInfo\x12\x15\n\rexternal_icon\x18\x01 \x01(\t\x12)\n\x06status\x18\x02 \x01(\x0e\x32\x19.proto.ExternalIconStatus\x12.\n\tshow_type\x18\x03 \x01(\x0e\x32\x1b.proto.ExternalIconShowType\"\xcc\x01\n\x14LeaderboardTitleInfo\x12\x1f\n\x17weapon_power_title_info\x18\x01 \x03(\r\x12\x1c\n\x14guild_war_title_info\x18\x02 \x03(\r\x12\x1a\n\x12ranking_title_info\x18\x03 \x03(\r\x12\x1b\n\x13title_first_receive\x18\x04 \x01(\x08\x12\x1a\n\x12\x63s_peak_title_info\x18\x05 \x03(\r\x12 \n\x18peak_title_first_receive\x18\x06 \x01(\x08\"\xbb\x03\n\x0fSocialBasicInfo\x12\x12\n\naccount_id\x18\x01 \x01(\x04\x12\x1d\n\x06gender\x18\x02 \x01(\x0e\x32\r.proto.Gender\x12\x10\n\x08language\x18\x03 \x01(\r\x12&\n\x0btime_online\x18\x04 \x01(\x0e\x32\x11.proto.TimeOnline\x12&\n\x0btime_active\x18\x05 \x01(\x0e\x32\x11.proto.TimeActive\x12\x12\n\nbattle_tag\x18\x06 \x03(\r\x12\x12\n\nsocial_tag\x18\x07 \x03(\r\x12&\n\x0bmode_prefer\x18\x08 \x01(\x0e\x32\x11.proto.ModePrefer\x12\x11\n\tsignature\x18\t \x01(\t\x12\"\n\trank_show\x18\n \x01(\x0e\x32\x0f.proto.RankShow\x12\x18\n\x10\x62\x61ttle_tag_count\x18\x0b \x03(\r\x12!\n\x19signature_ban_expire_time\x18\x0c \x01(\x03\x12\x37\n\x12leaderboard_titles\x18\r \x01(\x0b\x32\x1b.proto.LeaderboardTitleInfo\x12\x16\n\x0ephoto_wall_url\x18\x0e \x01(\t\"t\n#SocialHighLightsWithSocialBasicInfo\x12\x1a\n\x12social_high_lights\x18\x01 \x03(\r\x12\x31\n\x11social_basic_info\x18\x02 \x01(\x0b\x32\x16.proto.SocialBasicInfo\"C\n\tBadgeInfo\x12$\n\nbadge_type\x18\x01 \x01(\x0e\x32\x10.proto.BadgeType\x12\x10\n\x08sub_type\x18\x02 \x01(\r\"\xbc\x01\n\x14PrimePrivilegeDetail\x12\x12\n\naccount_id\x18\x01 \x01(\x04\x12\x13\n\x0bprime_level\x18\x02 \x01(\r\x12\x19\n\x11privilege_id_list\x18\x03 \x03(\r\x12\x16\n\x0emonthly_points\x18\x04 \x01(\x05\x12\x17\n\x0f\x61nnually_points\x18\x05 \x01(\x05\x12\x12\n\nsum_points\x18\x06 \x01(\x05\x12\x1b\n\x13sharee_remain_times\x18\x07 \x01(\r\"\xbe\x01\n\x0c\x42lacklistRes\x12\x12\n\naccount_id\x18\x01 \x01(\x04\x12\x11\n\tdevice_id\x18\x02 \x01(\t\x12\x12\n\nban_reason\x18\x03 \x01(\r\x12\x10\n\x08\x62\x61n_time\x18\x04 \x01(\r\x12\x19\n\x11\x62\x61n_reason_detail\x18\x05 \x01(\t\x12\x17\n\x0fis_in_blacklist\x18\x06 \x01(\x08\x12\x1b\n\x13\x62\x61n_expire_duration\x18\x07 \x01(\r\x12\x10\n\x08\x62\x61n_type\x18\x08 \x01(\t\"6\n\x18\x43reatorPrivilegeSwitches\x12\x1a\n\x12\x64isable_name_color\x18\x01 \x01(\x08\"\x91\x01\n\x1aWorkshopAccountSummaryInfo\x12\x12\n\naccount_id\x18\x01 \x01(\x04\x12\x0b\n\x03\x65xp\x18\x02 \x01(\r\x12\x15\n\rcreator_level\x18\x03 \x01(\r\x12;\n\x12privilege_switches\x18\x04 \x01(\x0b\x32\x1f.proto.CreatorPrivilegeSwitches\"\xa6\x02\n\tSparkInfo\x12 \n\x05state\x18\x01 \x01(\x0e\x32\x11.proto.SparkState\x12\r\n\x05level\x18\x02 \x01(\r\x12\x0b\n\x03\x65xp\x18\x03 \x01(\x04\x12\x19\n\x11login_streak_days\x18\x04 \x01(\r\x12\x0e\n\x06temper\x18\x05 \x01(\r\x12\x1b\n\x13\x61ppearance_item_ids\x18\x06 \x03(\r\x12 \n\x18\x64ormant_recover_progress\x18\x07 \x01(\r\x12%\n\x1d\x65xtinguished_recover_progress\x18\x08 \x01(\r\x12\x18\n\x10\x61ppearance_stage\x18\t \x01(\r\x12\x1e\n\x16stage_appearance_items\x18\n \x03(\r\x12\x10\n\x08\x63olor_id\x18\x0b \x01(\r\"S\n\x15\x41\x63\x63ountBasicSparkInfo\x12\x0f\n\x07\x63laimed\x18\x01 \x01(\x08\x12)\n\x0fuser_spark_info\x18\x02 \x01(\x0b\x32\x10.proto.SparkInfo\"\xa8\x12\n\x10\x41\x63\x63ountInfoBasic\x12\x12\n\naccount_id\x18\x01 \x01(\x04\x12\x14\n\x0c\x61\x63\x63ount_type\x18\x02 \x01(\r\x12\x10\n\x08nickname\x18\x03 \x01(\t\x12\x13\n\x0b\x65xternal_id\x18\x04 \x01(\t\x12\x0e\n\x06region\x18\x05 \x01(\t\x12\r\n\x05level\x18\x06 \x01(\r\x12\x0b\n\x03\x65xp\x18\x07 \x01(\r\x12\x15\n\rexternal_type\x18\x08 \x01(\r\x12\x15\n\rexternal_name\x18\t \x01(\t\x12\x15\n\rexternal_icon\x18\n \x01(\t\x12\x11\n\tbanner_id\x18\x0b \x01(\r\x12\x10\n\x08head_pic\x18\x0c \x01(\r\x12\x11\n\tclan_name\x18\r \x01(\t\x12\x0c\n\x04rank\x18\x0e \x01(\r\x12\x16\n\x0eranking_points\x18\x0f \x01(\r\x12\x0c\n\x04role\x18\x10 \x01(\r\x12\x16\n\x0ehas_elite_pass\x18\x11 \x01(\x08\x12\x11\n\tbadge_cnt\x18\x12 \x01(\r\x12\x10\n\x08\x62\x61\x64ge_id\x18\x13 \x01(\r\x12\x11\n\tseason_id\x18\x14 \x01(\r\x12\r\n\x05liked\x18\x15 \x01(\r\x12\x12\n\nis_deleted\x18\x16 \x01(\x08\x12\x11\n\tshow_rank\x18\x17 \x01(\x08\x12\x15\n\rlast_login_at\x18\x18 \x01(\x03\x12\x14\n\x0c\x65xternal_uid\x18\x19 \x01(\x04\x12\x11\n\treturn_at\x18\x1a \x01(\x03\x12\x1e\n\x16\x63hampionship_team_name\x18\x1b \x01(\t\x12$\n\x1c\x63hampionship_team_member_num\x18\x1c \x01(\r\x12\x1c\n\x14\x63hampionship_team_id\x18\x1d \x01(\x04\x12\x0f\n\x07\x63s_rank\x18\x1e \x01(\r\x12\x19\n\x11\x63s_ranking_points\x18\x1f \x01(\r\x12\x19\n\x11weapon_skin_shows\x18  \x03(\r\x12\x0e\n\x06pin_id\x18! \x01(\r\x12\x19\n\x11is_cs_ranking_ban\x18\" \x01(\x08\x12\x10\n\x08max_rank\x18# \x01(\r\x12\x13\n\x0b\x63s_max_rank\x18$ \x01(\r\x12\x1a\n\x12max_ranking_points\x18% \x01(\r\x12\x15\n\rgame_bag_show\x18& \x01(\r\x12\x15\n\rpeak_rank_pos\x18\' \x01(\r\x12\x18\n\x10\x63s_peak_rank_pos\x18( \x01(\r\x12.\n\x0f\x61\x63\x63ount_prefers\x18) \x01(\x0b\x32\x15.proto.AccountPrefers\x12\x1f\n\x17periodic_ranking_points\x18* \x01(\r\x12\x15\n\rperiodic_rank\x18+ \x01(\r\x12\x11\n\tcreate_at\x18, \x01(\x03\x12\x37\n\x16veteran_leave_days_tag\x18- \x01(\x0e\x32\x17.proto.VeteranLeaveDays\x12\x1b\n\x13selected_item_slots\x18. \x03(\r\x12\x35\n\x10pre_veteran_type\x18/ \x01(\x0e\x32\x1b.proto.PreVeteranActionType\x12\r\n\x05title\x18\x30 \x01(\r\x12\x33\n\x12\x65xternal_icon_info\x18\x31 \x01(\x0b\x32\x17.proto.ExternalIconInfo\x12\x17\n\x0frelease_version\x18\x32 \x01(\t\x12\x1b\n\x13veteran_expire_time\x18\x33 \x01(\x04\x12\x14\n\x0cshow_br_rank\x18\x34 \x01(\x08\x12\x14\n\x0cshow_cs_rank\x18\x35 \x01(\x08\x12\x0f\n\x07\x63lan_id\x18\x36 \x01(\x04\x12\x15\n\rclan_badge_id\x18\x37 \x01(\r\x12\x19\n\x11\x63ustom_clan_badge\x18\x38 \x01(\t\x12\x1d\n\x15use_custom_clan_badge\x18\x39 \x01(\x08\x12\x15\n\rclan_frame_id\x18: \x01(\r\x12\x18\n\x10membership_state\x18; \x01(\x08\x12\x1a\n\x12select_occupations\x18< \x03(\r\x12V\n\"social_high_lights_with_basic_info\x18= \x01(\x0b\x32*.proto.SocialHighLightsWithSocialBasicInfo\x12\x17\n\x0f\x61\x62_test_choices\x18> \x03(\r\x12\x15\n\ritem_tag_info\x18? \x03(\r\x12\x11\n\trank_sort\x18@ \x01(\r\x12\x14\n\x0c\x63s_rank_sort\x18\x41 \x01(\r\x12\x12\n\nhippo_rank\x18\x42 \x01(\r\x12\x1c\n\x14hippo_ranking_points\x18\x43 \x01(\r\x12\x16\n\x0ehippo_max_rank\x18\x44 \x01(\r\x12\x17\n\x0fshow_hippo_rank\x18\x45 \x01(\x08\x12\x1a\n\x12hippo_total_profit\x18\x46 \x01(\r\x12\x19\n\x11hippo_total_worth\x18G \x01(\r\x12\x18\n\x10mode_stats_infos\x18H \x03(\r\x12$\n\nbadge_info\x18I \x01(\x0b\x32\x10.proto.BadgeInfo\x12;\n\x16prime_privilege_detail\x18J \x01(\x0b\x32\x1b.proto.PrimePrivilegeDetail\x12\x16\n\x0e\x63s_peak_points\x18K \x01(\r\x12\x1d\n\x15\x64isplay_cs_peak_point\x18L \x01(\x08\x12#\n\x1b\x63s_peak_tournament_rank_pos\x18M \x01(\r\x12\x14\n\x0c\x61vatar_frame\x18N \x01(\r\x12&\n\tblacklist\x18O \x01(\x0b\x32\x13.proto.BlacklistRes\x12@\n\x15workshop_summary_info\x18P \x01(\x0b\x32!.proto.WorkshopAccountSummaryInfo\x12\x30\n\nspark_info\x18Q \x01(\x0b\x32\x1c.proto.AccountBasicSparkInfo\x12\x31\n\x11social_basic_info\x18R \x01(\x0b\x32\x16.proto.SocialBasicInfo\x12\x1f\n\x17photo_wall_ban_end_time\x18S \x01(\r\x12\x1a\n\x12show_emulator_flag\x18T \x01(\x08\x12\x1c\n\x14is_homepage_punished\x18U \x01(\x08\"\xca\x01\n\x14WorkshopCreatorStats\x12\x12\n\naccount_id\x18\x01 \x01(\x04\x12\x16\n\x0e\x66ollower_count\x18\x02 \x01(\r\x12\x0b\n\x03\x65xp\x18\x03 \x01(\r\x12\x13\n\x0blevel_infos\x18\x04 \x03(\r\x12\x15\n\rawarded_level\x18\x05 \x03(\r\x12\x0b\n\x03\x62io\x18\x06 \x01(\t\x12\x13\n\x0bpinned_maps\x18\x07 \x03(\r\x12\x18\n\x10latest_update_at\x18\x08 \x01(\x03\x12\x11\n\tmap_count\x18\t \x01(\r*P\n\x0c\x46ollowerType\x12\x15\n\x11\x46ollowerType_NONE\x10\x00\x12\x14\n\x10\x46ollowerType_YES\x10\x01\x12\x13\n\x0f\x46ollowerType_NO\x10\x02*\xa0\x01\n\x10VeteranLeaveDays\x12\x19\n\x15VeteranLeaveDays_NONE\x10\x00\x12\x1a\n\x16VeteranLeaveDays_SHORT\x10\x01\x12\x1b\n\x17VeteranLeaveDays_NORMAL\x10\x02\x12\x19\n\x15VeteranLeaveDays_LONG\x10\x03\x12\x1d\n\x19VeteranLeaveDays_VERYLONG\x10\x04*w\n\x14PreVeteranActionType\x12\x1d\n\x19PreVeteranActionType_NONE\x10\x00\x12!\n\x1dPreVeteranActionType_ACTIVITY\x10\x01\x12\x1d\n\x19PreVeteranActionType_BUFF\x10\x02*s\n\x12\x45xternalIconStatus\x12\x1b\n\x17\x45xternalIconStatus_NONE\x10\x00\x12!\n\x1d\x45xternalIconStatus_NOT_IN_USE\x10\x01\x12\x1d\n\x19\x45xternalIconStatus_IN_USE\x10\x02*t\n\x14\x45xternalIconShowType\x12\x1d\n\x19\x45xternalIconShowType_NONE\x10\x00\x12\x1f\n\x1b\x45xternalIconShowType_FRIEND\x10\x01\x12\x1c\n\x18\x45xternalIconShowType_ALL\x10\x02*T\n\x06Gender\x12\x0f\n\x0bGender_NONE\x10\x00\x12\x0f\n\x0bGender_MALE\x10\x01\x12\x11\n\rGender_FEMALE\x10\x02\x12\x15\n\x10Gender_UNLIMITED\x10\xe7\x07*l\n\nTimeOnline\x12\x13\n\x0fTimeOnline_NONE\x10\x00\x12\x16\n\x12TimeOnline_WORKDAY\x10\x01\x12\x16\n\x12TimeOnline_WEEKEND\x10\x02\x12\x19\n\x14TimeOnline_UNLIMITED\x10\xe7\x07*\x84\x01\n\nTimeActive\x12\x13\n\x0fTimeActive_NONE\x10\x00\x12\x16\n\x12TimeActive_MORNING\x10\x01\x12\x18\n\x14TimeActive_AFTERNOON\x10\x02\x12\x14\n\x10TimeActive_NIGHT\x10\x03\x12\x19\n\x14TimeActive_UNLIMITED\x10\xe7\x07*\x80\x01\n\nModePrefer\x12\x13\n\x0fModePrefer_NONE\x10\x00\x12\x11\n\rModePrefer_BR\x10\x01\x12\x11\n\rModePrefer_CS\x10\x02\x12\x1c\n\x18ModePrefer_ENTERTAINMENT\x10\x03\x12\x19\n\x14ModePrefer_UNLIMITED\x10\xe7\x07*X\n\x08RankShow\x12\x11\n\rRankShow_NONE\x10\x00\x12\x0f\n\x0bRankShow_BR\x10\x01\x12\x0f\n\x0bRankShow_CS\x10\x02\x12\x17\n\x12RankShow_UNLIMITED\x10\xe7\x07*R\n\tBadgeType\x12\x1a\n\x16\x42\x41\x44GE_TYPE_UNSPECIFIED\x10\x00\x12\x13\n\x0f\x42\x41\x44GE_TYPE_ROLE\x10\x01\x12\x14\n\x10\x42\x41\x44GE_TYPE_PRIME\x10\x02*m\n\nSparkState\x12\x13\n\x0fSparkState_NONE\x10\x00\x12\x15\n\x11SparkState_ACTIVE\x10\x01\x12\x16\n\x12SparkState_DORMANT\x10\x02\x12\x1b\n\x17SparkState_EXTINGUISHED\x10\x03\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'follow_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals['_FOLLOWERTYPE']._serialized_start = 4974
    _globals['_FOLLOWERTYPE']._serialized_end = 5054
    _globals['_VETERANLEAVEDAYS']._serialized_start = 5057
    _globals['_VETERANLEAVEDAYS']._serialized_end = 5217
    _globals['_PREVETERANACTIONTYPE']._serialized_start = 5219
    _globals['_PREVETERANACTIONTYPE']._serialized_end = 5338
    _globals['_EXTERNALICONSTATUS']._serialized_start = 5340
    _globals['_EXTERNALICONSTATUS']._serialized_end = 5455
    _globals['_EXTERNALICONSHOWTYPE']._serialized_start = 5457
    _globals['_EXTERNALICONSHOWTYPE']._serialized_end = 5573
    _globals['_GENDER']._serialized_start = 5575
    _globals['_GENDER']._serialized_end = 5659
    _globals['_TIMEONLINE']._serialized_start = 5661
    _globals['_TIMEONLINE']._serialized_end = 5769
    _globals['_TIMEACTIVE']._serialized_start = 5772
    _globals['_TIMEACTIVE']._serialized_end = 5904
    _globals['_MODEPREFER']._serialized_start = 5907
    _globals['_MODEPREFER']._serialized_end = 6035
    _globals['_RANKSHOW']._serialized_start = 6037
    _globals['_RANKSHOW']._serialized_end = 6125
    _globals['_BADGETYPE']._serialized_start = 6127
    _globals['_BADGETYPE']._serialized_end = 6209
    _globals['_SPARKSTATE']._serialized_start = 6211
    _globals['_SPARKSTATE']._serialized_end = 6320
    _globals['_CSFOLLOWREQ']._serialized_start = 23
    _globals['_CSFOLLOWREQ']._serialized_end = 55
    _globals['_CSFOLLOWRES']._serialized_start = 58
    _globals['_CSFOLLOWRES']._serialized_end = 246
    _globals['_ACCOUNTPREFERS']._serialized_start = 249
    _globals['_ACCOUNTPREFERS']._serialized_end = 475
    _globals['_EXTERNALICONINFO']._serialized_start = 478
    _globals['_EXTERNALICONINFO']._serialized_end = 610
    _globals['_LEADERBOARDTITLEINFO']._serialized_start = 613
    _globals['_LEADERBOARDTITLEINFO']._serialized_end = 817
    _globals['_SOCIALBASICINFO']._serialized_start = 820
    _globals['_SOCIALBASICINFO']._serialized_end = 1263
    _globals['_SOCIALHIGHLIGHTSWITHSOCIALBASICINFO']._serialized_start = 1265
    _globals['_SOCIALHIGHLIGHTSWITHSOCIALBASICINFO']._serialized_end = 1381
    _globals['_BADGEINFO']._serialized_start = 1383
    _globals['_BADGEINFO']._serialized_end = 1450
    _globals['_PRIMEPRIVILEGEDETAIL']._serialized_start = 1453
    _globals['_PRIMEPRIVILEGEDETAIL']._serialized_end = 1641
    _globals['_BLACKLISTRES']._serialized_start = 1644
    _globals['_BLACKLISTRES']._serialized_end = 1834
    _globals['_CREATORPRIVILEGESWITCHES']._serialized_start = 1836
    _globals['_CREATORPRIVILEGESWITCHES']._serialized_end = 1890
    _globals['_WORKSHOPACCOUNTSUMMARYINFO']._serialized_start = 1893
    _globals['_WORKSHOPACCOUNTSUMMARYINFO']._serialized_end = 2038
    _globals['_SPARKINFO']._serialized_start = 2041
    _globals['_SPARKINFO']._serialized_end = 2335
    _globals['_ACCOUNTBASICSPARKINFO']._serialized_start = 2337
    _globals['_ACCOUNTBASICSPARKINFO']._serialized_end = 2420
    _globals['_ACCOUNTINFOBASIC']._serialized_start = 2423
    _globals['_ACCOUNTINFOBASIC']._serialized_end = 4767
    _globals['_WORKSHOPCREATORSTATS']._serialized_start = 4770
    _globals['_WORKSHOPCREATORSTATS']._serialized_end = 4972

# ==================== ENCRYPTION KEYS ====================
_gAyKeY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
_gAyIv = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])
_hEhEuRl = "https://client.ind.freefiremobile.com/Follow"
_tOkEnApI = "https://ff-jwt-gen-api.lovable.app/api/public/token"

# ==================== FILE PATHS ====================
USERS_DATA_FILE = "users_data.json"
USED_UIDS_FILE = "used_uids.json"
CHANNELS_FILE = "channels.json"
CAPABLE_ACCOUNTS_FILE = "capable_accounts.json"
ALL_ACCOUNTS_FILE = "all_accounts.json"

# ==================== DEFAULT CHANNELS ====================
DEFAULT_CHANNELS = ["@SRK_ERA", "@SRKING000001", "@SRK_IMP1", "@snnetwork7", "@primeff55"]

# ==================== DATABASE FUNCTIONS ====================
def load_json_file(filepath: str, default=None):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default if default is not None else {}
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return default if default is not None else {}

def save_json_file(filepath: str, data):
    try:
        if os.path.exists(filepath):
            backup_path = filepath + ".bak"
            with open(filepath, 'r', encoding='utf-8') as f:
                old_data = f.read()
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(old_data)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving {filepath}: {e}")
        return False

def initialize_files():
    if not os.path.exists(CHANNELS_FILE):
        save_json_file(CHANNELS_FILE, DEFAULT_CHANNELS)
    
    if not os.path.exists(USERS_DATA_FILE):
        save_json_file(USERS_DATA_FILE, {"users": {}, "stats": {"total_users": 0, "verified_users": 0, "total_referrals": 0, "total_follows": 0}})
    
    if not os.path.exists(USED_UIDS_FILE):
        save_json_file(USED_UIDS_FILE, {"uids": {}})
    
    if not os.path.exists(CAPABLE_ACCOUNTS_FILE):
        save_json_file(CAPABLE_ACCOUNTS_FILE, {"accounts": [], "last_updated": None, "total": 0})

# ==================== HELPER FUNCTIONS ====================
def generate_referral_code(user_id: int) -> str:
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choices(chars, k=6))
    return code

def get_user_data(user_id: str) -> dict:
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    return data.get("users", {}).get(str(user_id), {})

def save_user_data(user_id: str, user_data: dict):
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    data["users"][str(user_id)] = user_data
    save_json_file(USERS_DATA_FILE, data)

def update_stats(stat_key: str, increment: int = 1):
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    data["stats"][stat_key] = data["stats"].get(stat_key, 0) + increment
    save_json_file(USERS_DATA_FILE, data)

def get_channels() -> list:
    return load_json_file(CHANNELS_FILE, DEFAULT_CHANNELS)

def get_jwt_from_account(account: dict) -> Optional[str]:
    if 'jwt' in account and account['jwt']:
        return account['jwt']
    if 'JwT_ToKeN' in account and account['JwT_ToKeN']:
        return account['JwT_ToKeN']
    return None

def is_uid_used(uid: str) -> bool:
    data = load_json_file(USED_UIDS_FILE, {"uids": {}})
    return str(uid) in data.get("uids", {})

def mark_uid_as_used(uid: str, followed_by: str):
    data = load_json_file(USED_UIDS_FILE, {"uids": {}})
    data["uids"][str(uid)] = {
        "followed_by": str(followed_by),
        "timestamp": datetime.now().isoformat(),
        "status": "success"
    }
    save_json_file(USED_UIDS_FILE, data)

# ==================== FOLLOW FUNCTIONS ====================
def _sHuFfLeShIt(dAtA: bytes) -> bytes:
    cIpHeR = AES.new(_gAyKeY, AES.MODE_CBC, _gAyIv)
    return cIpHeR.encrypt(pad(dAtA, AES.block_size))

def _gEtMyJwT(uId: int, pAsSwOrD: str) -> Optional[str]:
    pArAmS = {
        "guest_uid": str(uId),
        "guest_password": pAsSwOrD
    }
    try:
        rEsP = requests.get(_tOkEnApI, params=pArAmS, timeout=15)
        rEsP.raise_for_status()
        dAtA = rEsP.json()
        if dAtA.get("success") and dAtA.get("token"):
            return dAtA.get("token")
        return None
    except Exception:
        return None

def _dOtHeHeHe(tArGeT: int, jWt: str) -> Tuple[bool, str]:
    rEq = CSFollowReq()
    rEq.target_id = tArGeT
    eNcRyPtEd = _sHuFfLeShIt(rEq.SerializeToString())
    hEaDeRs = {
        "User-Agent": "UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "Authorization": f"Bearer {jWt}",
        "X-Ga": "v1 1",
        "Releaseversion": "OB54",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2022.3.47f1",
    }
    try:
        rEsP = requests.post(_hEhEuRl, headers=hEaDeRs, data=eNcRyPtEd, timeout=30)
        if rEsP.status_code != 200:
            return False, f"HTTP {rEsP.status_code}"
        rEs = CSFollowRes()
        rEs.ParseFromString(rEsP.content)
        if rEs.fail_info:
            return False, f"Server fail_info: {rEs.fail_info}"
        return True, ""
    except Exception as e:
        return False, f"Exception: {str(e)}"

def follow_with_account(account: dict, target_uid: int) -> Tuple[bool, str]:
    # Try stored JWT first
    jwt = get_jwt_from_account(account)
    
    if jwt:
        success, err = _dOtHeHeHe(target_uid, jwt)
        if success:
            return True, ""
    
    # If stored JWT failed, try generating new JWT from password
    uid = account.get("uid")
    pwd = account.get("password")
    
    if uid and pwd:
        try:
            new_jwt = _gEtMyJwT(int(uid), pwd)
            if new_jwt:
                success, err = _dOtHeHeHe(target_uid, new_jwt)
                if success:
                    # Update account with new JWT
                    account["jwt"] = new_jwt
                    return True, ""
                else:
                    return False, err
        except:
            pass
    
    return False, "Failed to follow"

def process_follow_target(target_uid: int, accounts: list) -> Tuple[int, int]:
    successful = 0
    already_followed = 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(follow_with_account, acc, target_uid): acc
            for acc in accounts
        }
        for future in as_completed(futures):
            success, err = future.result()
            if success:
                successful += 1
            elif "already" in err.lower():
                already_followed += 1
    
    return successful, already_followed

# ==================== COLORFUL BUTTON FUNCTIONS ====================
async def show_main_menu(message, user_id: str):
    user_data = get_user_data(user_id)
    points = user_data.get("referrals", {}).get("points", 0)
    referrals_count = user_data.get("referrals", {}).get("total_given", 0)
    follows_done = user_data.get("follows", {}).get("total_done", 0)
    
    can_follow = points >= POINTS_NEEDED_FOR_FOLLOW
    
    status_text = "✅ You have enough points! Click Get Followers." if can_follow else f"❌ You need {POINTS_NEEDED_FOR_FOLLOW - points} more points."
    
    message_text = f"""🎯 SRK FOLLOW BOT

👤 User: @{user_data.get('username', 'unknown')}
📊 Status: Verified ✅
👥 Referrals: {referrals_count}
💰 Points: {points}/{POINTS_NEEDED_FOR_FOLLOW}
🎯 Follows Done: {follows_done}

{status_text}
"""
    
    keyboard = [
        [InlineKeyboardButton("🔵 Get Followers", callback_data="get_followers", style="success")],
        [InlineKeyboardButton("👥 My Referrals", callback_data="my_referrals", style="primary"),
         InlineKeyboardButton("📊 My Status", callback_data="my_status", style="primary")],
        [InlineKeyboardButton("🔗 Referral Link", callback_data="referral_link", style="primary")],
        [InlineKeyboardButton("👨‍💻 Developer", callback_data="developer", style="primary")],
    ]
    
    if int(user_id) in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel", style="primary")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(message_text, reply_markup=reply_markup)

async def show_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, channels: list):
    keyboard = []
    for channel in channels:
        channel_name = channel.replace("@", "")
        keyboard.append([InlineKeyboardButton(text=f"📢 Join {channel}", url=f"https://t.me/{channel_name}", style="primary")])
    
    keyboard.append([InlineKeyboardButton(text="✅ Check Verification", callback_data="check_verification", style="success")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    channel_list = "\n".join([f"🔵 {ch}" for ch in channels])
    
    message = f"""🔥 SRK FOLLOW BOT

📌 Please join all active channels:

{channel_list}

After joining all channels, click Check Verification.
"""
    
    await update.message.reply_text(message, reply_markup=reply_markup)

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    
    user = update.effective_user
    user_id = str(user.id)
    
    user_data = get_user_data(user_id)
    if not user_data:
        user_data = {
            "username": user.username or "",
            "first_name": user.first_name or "",
            "joined_date": datetime.now().isoformat(),
            "joined_type": "direct",
            "referred_by": None,
            "referral_code": generate_referral_code(int(user_id)),
            "channels": {},
            "verified": False,
            "referrals": {
                "current_cycle": 1,
                "current_count": 0,
                "total_given": 0,
                "completed_cycles": 0,
                "referral_list": [],
                "points": 0
            },
            "follows": {
                "total_done": 0,
                "used_uids": [],
                "last_follow": None,
                "follows_history": []
            }
        }
        save_user_data(user_id, user_data)
        update_stats("total_users")
        
        if context.args:
            referrer_code = context.args[0]
            all_data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
            for uid, data in all_data["users"].items():
                if data.get("referral_code") == referrer_code:
                    user_data["referred_by"] = uid
                    user_data["joined_type"] = "referral"
                    save_user_data(user_id, user_data)
                    
                    referrer_data = all_data["users"][uid]
                    referrer_data["referrals"]["current_count"] += 1
                    referrer_data["referrals"]["total_given"] += 1
                    referrer_data["referrals"]["points"] += POINTS_PER_REFERRAL
                    referrer_data["referrals"]["referral_list"].append(user_id)
                    
                    if referrer_data["referrals"]["current_count"] >= REFERRALS_NEEDED:
                        referrer_data["referrals"]["completed_cycles"] += 1
                        referrer_data["referrals"]["current_count"] = 0
                        
                        for admin_id in ADMIN_IDS:
                            try:
                                await context.bot.send_message(
                                    chat_id=admin_id,
                                    text=f"🎉 User {referrer_data['username']} completed 5 referrals!\nTotal referrals: {referrer_data['referrals']['total_given']}"
                                )
                            except:
                                pass
                    
                    all_data["users"][uid] = referrer_data
                    save_json_file(USERS_DATA_FILE, all_data)
                    
                    try:
                        await context.bot.send_message(
                            chat_id=int(uid),
                            text=f"🎉 New referral joined!\nYou earned {POINTS_PER_REFERRAL} points!\nTotal points: {referrer_data['referrals']['points']}"
                        )
                    except:
                        pass
                    break
    
    channels = get_channels()
    await show_verification(update, context, channels)

async def check_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    channels = get_channels()
    
    all_joined = True
    not_joined = []
    
    for channel in channels:
        channel_name = channel.replace("@", "")
        try:
            member = await context.bot.get_chat_member(chat_id=f"@{channel_name}", user_id=query.from_user.id)
            if member.status in ['member', 'administrator', 'creator']:
                continue
            else:
                all_joined = False
                not_joined.append(channel)
        except:
            all_joined = False
            not_joined.append(channel)
    
    if all_joined:
        user_data = get_user_data(user_id)
        user_data["verified"] = True
        user_data["channels"] = {ch: True for ch in channels}
        save_user_data(user_id, user_data)
        
        data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
        data["stats"]["verified_users"] = data["stats"].get("verified_users", 0) + 1
        save_json_file(USERS_DATA_FILE, data)
        
        await query.edit_message_text(
            "✅ Verification Successful!\n\nYou can now use the bot.",
            reply_markup=None
        )
        
        await show_main_menu(query.message, user_id)
    else:
        not_joined_list = "\n".join([f"❌ {ch}" for ch in not_joined])
        await query.edit_message_text(
            f"❌ You haven't joined all channels yet!\n\nMissing channels:\n{not_joined_list}\n\nPlease join all channels and try again.",
            reply_markup=None
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    callback_data = query.data
    
    user_data = get_user_data(user_id)
    
    if not user_data.get("verified", False):
        await query.edit_message_text("⚠️ Please verify first by joining all channels!")
        return
    
    if callback_data == "get_followers":
        await handle_get_followers_callback(update, context)
    elif callback_data == "my_referrals":
        await handle_my_referrals_callback(update, context)
    elif callback_data == "my_status":
        await handle_my_status_callback(update, context)
    elif callback_data == "referral_link":
        await handle_referral_link_callback(update, context)
    elif callback_data == "developer":
        await handle_developer_callback(update, context)
    elif callback_data == "admin_panel":
        await handle_admin_panel_callback(update, context)
    elif callback_data == "admin_status":
        await handle_admin_status_callback(update, context)
    elif callback_data == "admin_users":
        await handle_admin_users_callback(update, context)
    elif callback_data == "admin_referrals":
        await handle_admin_referrals_callback(update, context)
    elif callback_data == "admin_verified":
        await handle_admin_verified_callback(update, context)
    elif callback_data == "admin_userlist":
        await handle_admin_userlist_callback(update, context)
    elif callback_data == "admin_refresh":
        await handle_admin_refresh_callback(update, context)
    elif callback_data == "admin_search":
        await handle_admin_search_callback(update, context)
    elif callback_data == "admin_broadcast":
        await handle_admin_broadcast_callback(update, context)
    elif callback_data == "credit_management":
        await handle_credit_management_callback(update, context)
    elif callback_data == "credit_add":
        await handle_credit_add_callback(update, context)
    elif callback_data == "credit_cut":
        await handle_credit_cut_callback(update, context)
    elif callback_data == "admin_upload":
        await handle_admin_upload_callback(update, context)
    elif callback_data == "admin_channels":
        await handle_admin_channels_callback(update, context)
    elif callback_data == "back_to_main":
        await query.edit_message_text("Main Menu")
        await show_main_menu(query.message, user_id)

async def handle_get_followers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    user_data = get_user_data(user_id)
    points = user_data.get("referrals", {}).get("points", 0)
    
    if points < POINTS_NEEDED_FOR_FOLLOW:
        needed = POINTS_NEEDED_FOR_FOLLOW - points
        await query.edit_message_text(
            f"❌ You need {needed} more points to get followers!\n\n"
            f"Current points: {points}/{POINTS_NEEDED_FOR_FOLLOW}\n"
            f"Refer people to earn points!"
        )
        return
    
    context.user_data["awaiting_uid"] = True
    context.user_data["awaiting_uid_message"] = query.message.message_id
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_follow", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎯 Enter Target UID to Follow:\n\n"
        "⚠️ Note: This UID will be saved, you cannot use it again.\n\n"
        "Example: 6377955722",
        reply_markup=reply_markup
    )

async def handle_my_referrals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    user_data = get_user_data(user_id)
    referrals = user_data.get("referrals", {})
    
    total_referrals = referrals.get("total_given", 0)
    points = referrals.get("points", 0)
    completed_cycles = referrals.get("completed_cycles", 0)
    
    text = f"""👥 MY REFERRALS

📊 Total Referrals: {total_referrals}
💰 Points: {points}/{POINTS_NEEDED_FOR_FOLLOW}
🔄 Completed Cycles: {completed_cycles}

📌 {REFERRALS_NEEDED} referrals = {POINTS_NEEDED_FOR_FOLLOW} points = Followers
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_my_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    user_data = get_user_data(user_id)
    
    text = f"""📊 MY STATUS

👤 User: @{user_data.get('username', 'unknown')}
✅ Verified: Yes
👥 Total Referrals: {user_data.get('referrals', {}).get('total_given', 0)}
💰 Points: {user_data.get('referrals', {}).get('points', 0)}/{POINTS_NEEDED_FOR_FOLLOW}
🔄 Cycles: {user_data.get('referrals', {}).get('completed_cycles', 0)}
🎯 Follows Done: {user_data.get('follows', {}).get('total_done', 0)}
📅 Joined: {user_data.get('joined_date', 'N/A')}
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_referral_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    user_data = get_user_data(user_id)
    referral_code = user_data.get("referral_code", "")
    
    bot_username = context.bot.username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    text1 = f"""🔗 YOUR REFERRAL LINK

Share this link with your friends:
{referral_link}

📌 {POINTS_PER_REFERRAL} points per referral
📌 {REFERRALS_NEEDED} referrals = {POINTS_NEEDED_FOR_FOLLOW} points = Followers
"""
    
    keyboard1 = [[InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main", style="danger")]]
    reply_markup1 = InlineKeyboardMarkup(keyboard1)
    
    await query.edit_message_text(text1, reply_markup=reply_markup1)
    
    text2 = f"""🔥 SRK FREE FOLLOWERS

Get Free Followers & Craft Accounts!
Join now and earn rewards!

🎯 10 Points per referral
💰 50 Points = Free Followers
🔄 Unlimited Cycles
"""
    
    keyboard2 = [
        [InlineKeyboardButton("🟢 Join and Earn", url=referral_link, style="success")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main", style="danger")]
    ]
    reply_markup2 = InlineKeyboardMarkup(keyboard2)
    
    await query.message.reply_text(text2, reply_markup=reply_markup2)

async def handle_developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    text = f"""👨‍💻 DEVELOPER

Contact the developer:
{DEVELOPER_USERNAME}
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

# ==================== ADMIN CALLBACK HANDLERS ====================
async def handle_admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    if int(user_id) not in ADMIN_IDS:
        await query.edit_message_text("❌ You are not authorized!")
        return
    
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    stats = data.get("stats", {})
    accounts_data = load_json_file(CAPABLE_ACCOUNTS_FILE, {"accounts": [], "last_updated": None, "total": 0})
    
    text = f"""⚙️ ADMIN PANEL

📌 Total Users: {stats.get('total_users', 0)}
✅ Verified: {stats.get('verified_users', 0)}
📈 Total Referrals: {stats.get('total_referrals', 0)}
🎯 Total Follows: {stats.get('total_follows', 0)}
📂 Capable Accounts: {len(accounts_data.get('accounts', []))}
"""
    
    keyboard = [
        [InlineKeyboardButton("📊 Status Check", callback_data="admin_status", style="primary")],
        [InlineKeyboardButton("👥 Total Users", callback_data="admin_users", style="primary"),
         InlineKeyboardButton("📈 Total Referrals", callback_data="admin_referrals", style="primary")],
        [InlineKeyboardButton("✅ Verified Users", callback_data="admin_verified", style="primary")],
        [InlineKeyboardButton("📋 User List", callback_data="admin_userlist", style="primary"),
         InlineKeyboardButton("🔄 Refresh Data", callback_data="admin_refresh", style="primary")],
        [InlineKeyboardButton("🔍 Search User", callback_data="admin_search", style="primary"),
         InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast", style="primary")],
        [InlineKeyboardButton("💳 Credit Management", callback_data="credit_management", style="primary")],
        [InlineKeyboardButton("📤 Upload Accounts", callback_data="admin_upload", style="primary"),
         InlineKeyboardButton("📌 Channel Management", callback_data="admin_channels", style="primary")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main", style="danger")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_admin_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    stats = data.get("stats", {})
    users = data.get("users", {})
    channels = get_channels()
    
    channel_stats = {}
    for channel in channels:
        channel_stats[channel] = sum(1 for u in users.values() if u.get("channels", {}).get(channel, False))
    
    text = f"""📊 STATUS CHECK

📌 Total Users: {stats.get('total_users', 0)}
✅ Verified Users: {stats.get('verified_users', 0)}
📈 Total Referrals: {stats.get('total_referrals', 0)}
🎯 Total Follows: {stats.get('total_follows', 0)}

Channel-wise:
"""
    for ch, count in channel_stats.items():
        text += f"\n{ch}: {count} members"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    users = data.get("users", {})
    
    if not users:
        await query.edit_message_text("No users yet!")
        return
    
    text = "👥 ALL USERS:\n\n"
    for uid, u in users.items():
        verified = "✅" if u.get("verified", False) else "❌"
        text += f"{verified} @{u.get('username', 'unknown')} (ID: {uid})\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if len(text) > 4000:
        text = text[:4000] + "...\n(Too many users to display)"
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_admin_referrals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    users = data.get("users", {})
    
    top_referrers = sorted(users.items(), key=lambda x: x[1].get("referrals", {}).get("total_given", 0), reverse=True)[:10]
    
    text = f"📈 TOP REFERRERS:\n\n"
    for i, (uid, u) in enumerate(top_referrers, 1):
        refs = u.get("referrals", {}).get("total_given", 0)
        points = u.get("referrals", {}).get("points", 0)
        text += f"{i}. @{u.get('username', 'unknown')} - {refs} referrals, {points} points\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_admin_verified_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    users = data.get("users", {})
    
    verified = [u for u in users.values() if u.get("verified", False)]
    
    text = f"✅ VERIFIED USERS: {len(verified)}\n\n"
    for u in verified:
        text += f"@{u.get('username', 'unknown')}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def handle_admin_userlist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_admin_users_callback(update, context)

async def handle_admin_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("✅ Data refreshed!")
    await handle_admin_panel_callback(update, context)

async def handle_admin_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["awaiting_search"] = True
    
    await query.edit_message_text("Enter username or UID to search:")

async def handle_admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["awaiting_broadcast"] = True
    
    await query.edit_message_text("Enter broadcast message to send to all users:")

async def handle_credit_management_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    if int(user_id) not in ADMIN_IDS:
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Credit", callback_data="credit_add", style="success")],
        [InlineKeyboardButton("➖ Cut Credit", callback_data="credit_cut", style="danger")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style="danger")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("💳 CREDIT MANAGEMENT\n\nChoose action:", reply_markup=reply_markup)

async def handle_credit_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["credit_action"] = "add"
    
    await query.edit_message_text("Enter user ID and points to add:\n\nFormat: user_id points\nExample: 123456789 50")

async def handle_credit_cut_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["credit_action"] = "cut"
    
    await query.edit_message_text("Enter user ID and points to cut:\n\nFormat: user_id points\nExample: 123456789 20")

async def handle_admin_upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["awaiting_accounts_upload"] = True
    
    await query.edit_message_text("Please send the JSON file with accounts:")

async def handle_admin_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    channels = get_channels()
    
    text = "📌 ACTIVE CHANNELS:\n\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. {ch}\n"
    text += "\nUse commands:\n/add_channel @channel\n/remove_channel @channel\n/list_channels"
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel", style="danger")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

# ==================== TEXT HANDLERS ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    
    user = update.effective_user
    user_id = str(user.id)
    text = update.message.text
    
    if context.user_data.get("awaiting_uid"):
        await handle_uid_input(update, context)
    elif context.user_data.get("awaiting_broadcast"):
        await handle_broadcast_input(update, context)
    elif context.user_data.get("awaiting_search"):
        await handle_search_input(update, context)
    elif context.user_data.get("credit_action"):
        await handle_credit_input(update, context)
    elif text == "/start":
        await start(update, context)

async def handle_uid_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    try:
        target_uid = int(text)
    except ValueError:
        await update.message.reply_text("❌ Invalid UID! Please enter a valid number.")
        return
    
    if is_uid_used(str(target_uid)):
        await update.message.reply_text(f"❌ You have already followed UID: {target_uid}")
        context.user_data["awaiting_uid"] = False
        await show_main_menu(update.message, user_id)
        return
    
    accounts_data = load_json_file(CAPABLE_ACCOUNTS_FILE, {"accounts": [], "last_updated": None, "total": 0})
    accounts = accounts_data.get("accounts", [])
    
    if not accounts:
        await update.message.reply_text("❌ No accounts available! Please contact admin.")
        context.user_data["awaiting_uid"] = False
        await show_main_menu(update.message, user_id)
        return
    
    await update.message.reply_text(f"🔄 Processing follow for UID: {target_uid}\n\nPlease wait...")
    
    def do_follow():
        return process_follow_target(target_uid, accounts)
    
    loop = asyncio.get_event_loop()
    successful, already_followed = await loop.run_in_executor(None, do_follow)
    
    mark_uid_as_used(str(target_uid), user_id)
    
    user_data = get_user_data(user_id)
    user_data["follows"]["total_done"] += successful
    user_data["follows"]["used_uids"].append(str(target_uid))
    user_data["follows"]["last_follow"] = datetime.now().isoformat()
    user_data["referrals"]["points"] = 0
    user_data["referrals"]["current_count"] = 0
    save_user_data(user_id, user_data)
    
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    data["stats"]["total_follows"] = data["stats"].get("total_follows", 0) + successful
    save_json_file(USERS_DATA_FILE, data)
    
    context.user_data["awaiting_uid"] = False
    
    result_text = f"""✅ FOLLOW RESULTS

📊 Summary:
├─ ✅ Successfully Followed: {successful}
└─ ⚠️ Already Followed: {already_followed}

🎯 Target UID: {target_uid}
📌 Total Followers Gained: {successful}
🔄 Next cycle: {POINTS_NEEDED_FOR_FOLLOW} more points needed.
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main", style="primary")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(result_text, reply_markup=reply_markup)

async def handle_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    broadcast_text = update.message.text.strip()
    context.user_data["awaiting_broadcast"] = False
    
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    users = data.get("users", {})
    
    sent_count = 0
    for uid in users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 BROADCAST:\n\n{broadcast_text}")
            sent_count += 1
        except:
            pass
    
    await update.message.reply_text(f"✅ Broadcast sent to {sent_count} users!")
    await show_main_menu(update.message, str(update.effective_user.id))

async def handle_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_term = update.message.text.strip()
    context.user_data["awaiting_search"] = False
    
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    users = data.get("users", {})
    
    found = []
    for uid, u in users.items():
        if search_term.lower() in str(uid) or search_term.lower() in u.get("username", "").lower():
            found.append((uid, u))
    
    if not found:
        await update.message.reply_text("❌ No users found!")
        return
    
    text = f"🔍 SEARCH RESULTS: {len(found)}\n\n"
    for uid, u in found:
        verified = "✅" if u.get("verified", False) else "❌"
        refs = u.get("referrals", {}).get("total_given", 0)
        points = u.get("referrals", {}).get("points", 0)
        text += f"{verified} @{u.get('username', 'unknown')}\n"
        text += f"   ID: {uid}\n"
        text += f"   Referrals: {refs}, Points: {points}\n\n"
    
    await update.message.reply_text(text)
    await show_main_menu(update.message, str(update.effective_user.id))

async def handle_credit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    action = context.user_data.get("credit_action")
    
    try:
        parts = text.split()
        target_user_id = parts[0]
        points = int(parts[1])
    except:
        await update.message.reply_text("❌ Invalid format! Use: user_id points")
        return
    
    target_user_data = get_user_data(target_user_id)
    if not target_user_data:
        await update.message.reply_text("❌ User not found!")
        context.user_data["credit_action"] = None
        return
    
    current_points = target_user_data.get("referrals", {}).get("points", 0)
    
    if action == "add":
        target_user_data["referrals"]["points"] = current_points + points
        await update.message.reply_text(f"✅ Added {points} points to user {target_user_id}!\nNew balance: {current_points + points}")
    elif action == "cut":
        new_points = max(0, current_points - points)
        target_user_data["referrals"]["points"] = new_points
        await update.message.reply_text(f"✅ Cut {points} points from user {target_user_id}!\nNew balance: {new_points}")
    
    save_user_data(target_user_id, target_user_data)
    context.user_data["credit_action"] = None
    
    try:
        await context.bot.send_message(
            chat_id=int(target_user_id),
            text=f"💳 Credit Update!\nPoints: {current_points} → {target_user_data['referrals']['points']}"
        )
    except:
        pass
    
    await show_main_menu(update.message, str(update.effective_user.id))

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    
    user_id = str(update.effective_user.id)
    if int(user_id) not in ADMIN_IDS:
        return
    
    if not update.message.document:
        return
    
    document = update.message.document
    
    if document.file_size > 50 * 1024 * 1024:
        await update.message.reply_text("❌ File too large! Maximum 50MB allowed.")
        return
    
    await update.message.reply_text("📥 Downloading file...")
    
    try:
        file = await context.bot.get_file(document.file_id, read_timeout=60, write_timeout=60, connect_timeout=60, pool_timeout=60)
        file_path = f"temp_{document.file_name}"
        await file.download_to_drive(file_path, read_timeout=60, write_timeout=60, connect_timeout=60)
    except Exception as e:
        await update.message.reply_text(f"❌ Download failed: {str(e)}")
        return
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
        
        if not isinstance(accounts, list):
            await update.message.reply_text("❌ Invalid format! Expected JSON array.")
            os.remove(file_path)
            return
        
        save_json_file(ALL_ACCOUNTS_FILE, accounts)
        
        accounts_data = {
            "accounts": accounts,
            "last_updated": datetime.now().isoformat(),
            "total": len(accounts)
        }
        save_json_file(CAPABLE_ACCOUNTS_FILE, accounts_data)
        
        await update.message.reply_text(f"✅ Accounts uploaded successfully!\n\nTotal accounts: {len(accounts)}")
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📤 File uploaded: {document.file_name}\nTotal accounts: {len(accounts)}"
                )
            except:
                pass
        
    except json.JSONDecodeError as e:
        await update.message.reply_text(f"❌ Invalid JSON file: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")
    
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

# ==================== COMMAND HANDLERS ====================
async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    
    user_id = str(update.effective_user.id)
    if int(user_id) not in ADMIN_IDS:
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /add_channel @channel")
        return
    
    channel = context.args[0]
    channels = get_channels()
    
    if len(channels) >= MAX_CHANNELS:
        await update.message.reply_text(f"❌ Maximum {MAX_CHANNELS} channels allowed!")
        return
    
    if channel in channels:
        await update.message.reply_text("❌ Channel already exists!")
        return
    
    if not channel.startswith("@"):
        channel = "@" + channel
    
    channels.append(channel)
    save_json_file(CHANNELS_FILE, channels)
    
    await update.message.reply_text(f"✅ Channel {channel} added!")

async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    
    user_id = str(update.effective_user.id)
    if int(user_id) not in ADMIN_IDS:
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /remove_channel @channel")
        return
    
    channel = context.args[0]
    channels = get_channels()
    
    if channel not in channels:
        await update.message.reply_text("❌ Channel not found!")
        return
    
    channels.remove(channel)
    save_json_file(CHANNELS_FILE, channels)
    
    await update.message.reply_text(f"✅ Channel {channel} removed!")

async def list_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    
    user_id = str(update.effective_user.id)
    if int(user_id) not in ADMIN_IDS:
        return
    
    channels = get_channels()
    
    text = "📌 ACTIVE CHANNELS:\n\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. {ch}\n"
    
    await update.message.reply_text(text)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    
    user_id = str(update.effective_user.id)
    if int(user_id) not in ADMIN_IDS:
        return
    
    data = load_json_file(USERS_DATA_FILE, {"users": {}, "stats": {}})
    stats = data.get("stats", {})
    accounts_data = load_json_file(CAPABLE_ACCOUNTS_FILE, {"accounts": [], "last_updated": None, "total": 0})
    
    text = f"""⚙️ ADMIN PANEL

📌 Total Users: {stats.get('total_users', 0)}
✅ Verified: {stats.get('verified_users', 0)}
📈 Total Referrals: {stats.get('total_referrals', 0)}
🎯 Total Follows: {stats.get('total_follows', 0)}
📂 Capable Accounts: {len(accounts_data.get('accounts', []))}
"""
    
    keyboard = [
        [InlineKeyboardButton("📊 Status Check", callback_data="admin_status", style="primary")],
        [InlineKeyboardButton("👥 Total Users", callback_data="admin_users", style="primary"),
         InlineKeyboardButton("📈 Total Referrals", callback_data="admin_referrals", style="primary")],
        [InlineKeyboardButton("✅ Verified Users", callback_data="admin_verified", style="primary")],
        [InlineKeyboardButton("📋 User List", callback_data="admin_userlist", style="primary"),
         InlineKeyboardButton("🔄 Refresh Data", callback_data="admin_refresh", style="primary")],
        [InlineKeyboardButton("🔍 Search User", callback_data="admin_search", style="primary"),
         InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast", style="primary")],
        [InlineKeyboardButton("💳 Credit Management", callback_data="credit_management", style="primary")],
        [InlineKeyboardButton("📤 Upload Accounts", callback_data="admin_upload", style="primary"),
         InlineKeyboardButton("📌 Channel Management", callback_data="admin_channels", style="primary")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main", style="danger")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)

# ==================== MAIN FUNCTION ====================
def main():
    initialize_files()
    
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )
    
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if update and update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ An error occurred. Please try again."
                )
        except:
            pass
        print(f"Error: {context.error}")
    
    application.add_error_handler(error_handler)
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("add_channel", add_channel_command))
    application.add_handler(CommandHandler("remove_channel", remove_channel_command))
    application.add_handler(CommandHandler("list_channels", list_channels_command))
    application.add_handler(CallbackQueryHandler(check_verification, pattern="check_verification"))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file_upload))
    
    print("🤖 Bot started!")
    application.run_polling()

if __name__ == "__main__":
    main()
