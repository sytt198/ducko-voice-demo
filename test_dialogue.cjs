const assert=require('node:assert/strict');
const {route}=require('./dialogue-engine.js');
const cases=[
 ['介绍宁诺','zh',{},'overview'],
 ['宁 波 诺 丁 汉 大 学','zh',{},'overview'],
 ['它在哪里','zh',{lastId:'overview'},'location'],
 ['他在哪里','zh',{lastId:'overview'},'location'],
 ['校园在哪里','zh',{},'location'],
 ['学校学费多少钱','zh',{},'unknown'],
 ['What is the tuition fee at UNNC?','en',{},'unknown'],
 ['Where is the campus?','en',{},'location'],
 ['它在哪里','zh',{lastId:'equipment'},'unknown'],
 ['再说一遍','zh',{lastId:'visit_rules'},'visit_rules'],
 ['再说一遍','zh',{},'unknown'],
 ['学校研究什么','zh',{},'research'],
 ['这台设备是什么','zh',{},'equipment'],
 ['参观要注意什么','zh',{},'visit_rules'],
 ['你能做什么','zh',{},'abilities'],
 ['开始导览','zh',{},'tour_start'],
 ['结束参观','zh',{},'farewell'],
 ['What are the visit rules?','en',{},'visit_rules'],
 ['Where is it?','en',{lastId:'overview'},'location'],
 ['What can you do?','en',{},'abilities'],
 ['What is the tuition fee?','en',{},'unknown'],
 ['明天实验室几点开门','zh',{},'unknown']
];
for(const [q,l,ctx,id] of cases)assert.equal(route(q,l,ctx).id,id,q);
assert.equal(route('停止','zh').action,'stop');
assert.equal(route('慢一点','zh',{lastId:'overview'}).rate,.85);
assert.equal(route('结束对话','zh').end,true);
assert.equal(route('','zh').action,'empty');
assert.equal(route('谢谢','zh',{entries:[{id:'farewell',questions:{zh:['谢谢']}}]}).end,true);
console.log((cases.length+5)+' dialogue routing checks passed');
