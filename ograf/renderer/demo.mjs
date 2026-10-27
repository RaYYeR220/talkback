/**
 * Standalone sample rundown for eyeballing the graphics without a server (`?demo=1`).
 * It drives the same handlers the server's commands use. Clubs and players are fictional.
 */

const graphic = (id) => ({ id, main: new URL(`../graphics/${id}/graphic.mjs`, import.meta.url).href });
const L = { bug: { layer: 10 }, tag: { layer: 20 }, lower: { layer: 30 }, card: { layer: 40 }, ifb: { layer: 50 } };
const wait = (ms) => new Promise((done) => setTimeout(done, ms));

const ELSEWHERE = [
  { homeShort: "IRO", awayShort: "KES", homeScore: 1, awayScore: 0, minute: 71 },
  { homeShort: "FEN", awayShort: "WES", homeScore: 2, awayScore: 1, minute: 67 },
  { homeShort: "THO", awayShort: "RED", homeScore: 1, awayScore: 1, minute: 64 },
];

const EN = {
  bug: { homeShort: "CAL", awayShort: "ASH", homeScore: 0, awayScore: 0, minute: 63, homeColor: "#7a1f2b", awayColor: "#1f4e9c", elsewhere: ELSEWHERE },
  l3: { kicker: "Calder Vale", name: "Tomas Okafor", line: "Two goals in his last three starts" },
  tag: { name: "Okafor", number: "9", club: "CAL", clubColor: "#7a1f2b", speed: 31.4, distance: 9.8 },
  story: { kind: "Milestone", title: "One away from 100", line: "Tomas Okafor needs one more goal for his hundredth in senior football.", context: "Calder Vale v Ashcombe Rovers · 63′" },
  stat: { subject: "Tomas Okafor · CAL", label: "Pressures in the final third", value: "14", ratio: 0.7, compareLabel: "League average", compareValue: "9", compareRatio: 0.45, caption: "Most by any player in the round so far", evidence: "n=14 · 32′–41′" },
  cf: { metric: "Win probability · Calder Vale", title: "If the 38′ red card had not happened", asPlayed: 41, ifNot: 63, effect: "−22 pts", interval: "95% interval −34 to −9", evidence: "400 paired rollouts" },
  swing: { club: "Westmarsh Town", clubColor: "#0f6b4f", metric: "Relegation chance", before: 31, after: 54, tone: "bad", causedBy: "Ironmouth Athletic 1–0 Kestrel Bay Wanderers · 71′", caption: "Ironmouth's winner lifts them above Westmarsh." },
  ifb1: { label: "Story", text: "Okafor is one away from his hundredth career goal.", context: "CAL 0–0 ASH · 63′", countdownMs: 12000 },
  ifb2: { label: "Table", priority: "urgent", text: "Elsewhere: Ironmouth lead, Westmarsh drop into the bottom three as it stands.", context: "IRO 1–0 KES · 71′", countdownMs: 9000 },
};

const rtl = { dir: "rtl", lang: "ar" };
const AR = {
  bug: { ...EN.bug, ...rtl, asItStandsLabel: "حسب الوضع الحالي" },
  l3: { ...rtl, kicker: "كالدر فيل", name: "توماس أوكافور", line: "هدفان في آخر ثلاث مباريات أساسية" },
  tag: { ...EN.tag, ...rtl, name: "أوكافور", speedUnit: "كم/س", distanceUnit: "كم" },
  story: { ...rtl, kind: "إنجاز", title: "على بُعد هدف من المئة", line: "يحتاج أوكافور إلى هدف واحد لبلوغ هدفه المئة في مسيرته.", context: "كالدر فيل ضد آشكوم روفرز · 63′" },
  stat: { ...EN.stat, ...rtl, label: "الضغط في الثلث الأخير", compareLabel: "متوسط الدوري", caption: "الأعلى بين جميع اللاعبين في هذه الجولة" },
  cf: { ...EN.cf, ...rtl, metric: "احتمال الفوز · كالدر فيل", title: "لو لم تُشهَر البطاقة الحمراء في الدقيقة 38", asPlayedLabel: "كما جرت", ifNotLabel: "لو لم تحدث", effect: "−22 نقطة", interval: "فاصل 95%: من −34 إلى −9", evidence: "400 محاكاة مزدوجة" },
  swing: { ...EN.swing, ...rtl, club: "ويستمارش تاون", metric: "احتمال الهبوط", deltaUnit: " نقطة", causedByLabel: "بسبب", causedBy: "آيرونماوث 1–0 كيستريل باي · 71′", asItStandsLabel: "حسب الوضع الحالي", caption: "" },
  ifb1: { ...EN.ifb1, ...rtl, label: "قصة", text: "أوكافور على بُعد هدف واحد من هدفه المئة." },
  ifb2: { ...EN.ifb2, ...rtl, label: "الترتيب" },
};

export async function run({ handlers, rtl: useRtl = false, ifb = false }) {
  const T = useRtl ? AR : EN;
  const id = (name) => `demo-${name}`;
  const load = (name, graphicId, layer, data) =>
    handlers.load({ graphicInstanceId: id(name), renderTarget: layer, graphic: graphic(graphicId), params: { data } });
  const play = (name) => handlers.playAction({ graphicInstanceId: id(name), params: {} });
  const stop = (name) => handlers.stopAction({ graphicInstanceId: id(name), params: {} });
  const update = (name, data) => handlers.updateAction({ graphicInstanceId: id(name), params: { data } });
  const names = ["bug", "tag", "l3", "story", "stat", "cf", "swing", "ifb"];

  for (;;) {
    await load("bug", "talkback-scorebug", L.bug, T.bug);
    play("bug");
    await wait(800);
    await load("l3", "talkback-lower-third", L.lower, T.l3);
    play("l3");
    if (ifb) {
      await load("ifb", "talkback-ifb", L.ifb, T.ifb1);
      play("ifb");
    }
    await wait(1200);
    await load("tag", "talkback-player-tag", L.tag, { ...T.tag, x: 0.3, y: 0.62 });
    play("tag");
    for (let i = 0; i <= 25; i++) {
      update("tag", { x: 0.3 + i * 0.01, y: 0.62 - Math.sin(i / 8) * 0.06, speed: 28 + (i % 7) * 0.6 });
      await wait(200);
    }
    stop("tag");
    stop("l3");
    await wait(600);
    await load("story", "talkback-story-card", L.lower, T.story);
    play("story");
    await load("stat", "talkback-stat-card", L.card, T.stat);
    play("stat");
    await wait(3000);
    update("bug", { minute: 64, homeScore: 1 });
    await wait(5000);
    stop("stat");
    await wait(600);
    await load("cf", "talkback-counterfactual-card", L.card, T.cf);
    play("cf");
    await wait(2000);
    stop("story");
    if (ifb) {
      await load("ifb", "talkback-ifb", L.ifb, T.ifb2);
      play("ifb");
    }
    await wait(8000);
    stop("cf");
    await wait(600);
    update("bug", { asItStands: true, minute: 71 });
    await load("swing", "talkback-table-swing", L.card, T.swing);
    play("swing");
    await wait(8000);
    stop("swing");
    update("bug", { asItStands: false });
    if (ifb) stop("ifb");
    await wait(1500);
    await handlers.clear({ graphicInstanceIds: names.map(id) });
    await wait(1000);
  }
}
