/* 统计页与学习报告共用的纯派生逻辑，两处消费同一份 /stats 载荷。 */

/* 单日活跃量：听打 + 背单词的正误合计（热力图/有记录天数都用它） */
export function activity(d) {
  return (d.right || 0) + (d.wrong || 0) + (d.memorize_right || 0) + (d.memorize_wrong || 0);
}

/* 黄金时段：作答最多的小时，返回 "08" 这样的两位字符串；全天无作答返回 null。
   注意存索引而非计数——hours 下标才是小时数。 */
export function goldenHour(hours) {
  let best = -1;
  hours.forEach((n, i) => {
    if (n > 0 && (best < 0 || n > hours[best])) best = i;
  });
  return best < 0 ? null : String(best).padStart(2, "0");
}
