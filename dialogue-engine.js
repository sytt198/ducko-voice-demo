/* Small, explicit FAQ routing. This is not a generative language model. */
(function(root){
  'use strict';
  const normalize = text => String(text||'').toLowerCase().replace(/[\s，。！？、,.!?：:;；“”‘’'"-]/g,'');
  function routeImpl(text, language, context={}) {
    const q=normalize(text), last=context.lastId;
    if(!q)return {action:'empty'};
    if(/^(停止|停下|别说了|停|stop|cancel)$/.test(q))return {action:'stop'};
    if(/再说|再讲|重复|repeat|sayitagain/.test(q))return last?{action:'answer',id:last,repeat:true}:{action:'answer',id:'unknown'};
    if(/慢一点|慢点|slower|slowdown/.test(q))return last?{action:'answer',id:last,repeat:true,rate:.85}:{action:'answer',id:'unknown',rate:.85};
    if(/结束对话|结束参观|再见|拜拜|goodbye|bye|endconversation|endtour/.test(q))return {action:'answer',id:'farewell',end:true};
    if(/带.*参观|开始导览|开始参观|starttour|showmearound|takemeonatour/.test(q))return {action:'answer',id:'tour_start',tour:true};
    if(/安全|注意|须知|规则|safety|rules|careful/.test(q))return {action:'answer',id:'visit_rules'};
    if(/仪器|设备|器材|equipment|instrument|machine/.test(q))return {action:'answer',id:'equipment'};
    if(/研究|科研|research/.test(q))return {action:'answer',id:'research'};
    if(/^(它在哪里|他在哪里|她在哪里|那在哪|在哪里|在哪|whereisit|whereisthat)$/.test(q))return {action:'answer',id:['overview','location'].includes(last)?'location':'unknown'};
    const entries=context.entries||[];
    const exact=entries.find(entry=>(entry.questions?.[language]||[]).some(p=>normalize(p)===q));
    if(exact)return {action:'answer',id:exact.id};
    if(/学费|招生|录取|奖学金|排名|开放|开门|预约|tuition|admission|scholarship|ranking|opening|booking/.test(q))return {action:'answer',id:'unknown'};
    if(/地址|校园.*哪|学校.*哪|宁诺.*哪|诺丁汉.*哪|university.*where|where.*university|where.*campus|campus.*located|address/.test(q))return {action:'answer',id:'location'};
    if(/你.*(能|会|做|是谁)|功能|你叫什么|whoareyou|whatcanyoudo|yourname|capabilities/.test(q))return {action:'answer',id:'abilities'};
    if(/介绍.*(宁诺|诺丁汉|大学|校园|学校|unnc)|^(宁诺|宁波诺丁汉大学|unnc|学校|校园)$|about.*(unnc|university)|introduce.*(university|unnc)|学校.*成立|大学.*成立/.test(q))return {action:'answer',id:'overview'};
    return {action:'answer',id:'unknown'};
  }
  function route(...args){const result=routeImpl(...args);if(result.id==='farewell')result.end=true;if(result.id==='tour_start')result.tour=true;return result;}
  const api={route,normalize};root.DuckoDialogueEngine=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
