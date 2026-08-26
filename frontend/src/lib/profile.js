import { reactive } from "vue";
import { api } from "./core";

/* 词力档案（等级/树/活跃）共享单例：TopBar 徽章、单词树页、每日挑战结算共用，
   任何页面记录成绩后 dispatch "profile-changed" 事件即可让徽章刷新。 */
export const Profile = reactive({
  loading: true,
  ready: false,
  xp: 0, level: 1, title: "词童",
  levelFloor: 0, nextLevelXp: null, levelProgress: 0,
  streak: 0, todayDone: false, totalActiveDays: 0,
  treeStage: 0, treeMaxStage: 7, treeIcon: "🌰", treeLabel: "种子",
  treeWilted: false, treeNeedsWater: false,
  dailyCount: 0, dailyStreak: 0, dailyDoneToday: false,
  week: [],
});

export function applyProfile(d = {}) {
  Profile.xp = d.xp || 0;
  Profile.level = d.level || 1;
  Profile.title = d.title || "词童";
  Profile.levelFloor = d.level_floor || 0;
  Profile.nextLevelXp = d.next_level_xp ?? null;
  Profile.levelProgress = d.level_progress || 0;
  Profile.streak = d.streak || 0;
  Profile.todayDone = Boolean(d.today_done);
  Profile.totalActiveDays = d.total_active_days || 0;
  Profile.treeStage = d.tree_stage || 0;
  Profile.treeMaxStage = d.tree_max_stage ?? 7;
  Profile.treeIcon = d.tree_icon || "🌰";
  Profile.treeLabel = d.tree_label || "种子";
  Profile.treeWilted = Boolean(d.tree_wilted);
  Profile.treeNeedsWater = Boolean(d.tree_needs_water);
  Profile.dailyCount = d.daily_count || 0;
  Profile.dailyStreak = d.daily_streak || 0;
  Profile.dailyDoneToday = Boolean(d.daily_done_today);
  Profile.week = Array.isArray(d.week) ? d.week : [];
  Profile.ready = true;
  return Profile;
}

let inflight = null;

/** 拉取词力档案；force=false 时短路复用已有数据与在途请求。 */
export async function refreshProfile(force = false) {
  if (!force && (Profile.ready || inflight)) {
    return inflight || Promise.resolve(Profile);
  }
  Profile.loading = !Profile.ready;
  inflight = api("/profile").then((d) => {
    inflight = null;
    applyProfile(d);
    Profile.loading = false;
    return Profile;
  }).catch((err) => {
    inflight = null;
    Profile.loading = false;
    throw err;
  });
  return inflight;
}

export function applyDailyResult(profile) {
  /* 每日挑战提交成功后，用响应里随带的最新 profile 原地刷新，免二次请求 */
  if (profile) applyProfile(profile);
}
