export const meta = {
  name: 'blind-context-comprehension',
  description: '盲测: 7 个只看得到"简化后 agent 的 context + 工具 schema"的 agent, 各为 2 道题写出会发的工具调用, 用来检验这份 context 够不够让 agent 知道能干吗/怎么干/资源在哪',
  phases: [
    { title: 'Blind', detail: '每个 agent 只读两份 prompt 文件, 写出逐字可发送的调用序列和不清楚之处' },
  ],
}

const DIR = '/tmp/claude-1000/-home-ubuntu/7b2b543c-9f14-4731-9c56-595c154776f7/scratchpad/simple_agent/prompts'
const PAIRS = [
  ['Q01', 'Q08'], ['Q02', 'Q09'], ['Q03', 'Q10'], ['Q04', 'Q11'],
  ['Q05', 'Q12'], ['Q06', 'Q13'], ['Q07', 'Q14'],
]

const SCHEMA = {
  type: 'object',
  properties: {
    plans: { type: 'array', items: { type: 'object', properties: {
      qid: { type: 'string' },
      reading: { type: 'string' },
      steps: { type: 'array', items: { type: 'object', properties: {
        tool: { type: 'string' },
        args_json: { type: 'string' },
        purpose: { type: 'string' },
        depends_on: { type: 'string' },
        repeat: { type: 'string' },
        certainty: { type: 'string' },
        basis: { type: 'string' },
      }, required: ['tool', 'args_json', 'purpose', 'certainty', 'basis'] } },
      answer_shape: { type: 'string' },
      cannot: { type: 'string' },
      unclear: { type: 'array', items: { type: 'string' } },
    }, required: ['qid', 'reading', 'steps', 'answer_shape', 'unclear'] } },
    read_only_the_given_files: { type: 'boolean' },
  },
  required: ['plans', 'read_only_the_given_files'],
}

function promptFor(pair) {
  const files = pair.map(q => `${DIR}/${q}.txt`).join('\n')
  return `这是一个理解力实验。你要扮演一个 agent: 它在一轮对话开始时拿到的全部东西, 就是下面每个文件里的内容(三段 system 消息、工具的 function schema、用户的问题)。每个文件是一道独立的题, 两道题互不相关, 分别作答。

文件:
${files}

规则:
1. 只允许用 Read 读取上面列出的文件, 每个文件整份读完(文件较长, 需要的话分段读)。不要读任何其它文件或目录, 不要运行任何命令, 不要搜索代码库或网络。这个 agent 的世界里只有这份 context; 你如果看了别的东西, 实验就作废。你自己记得的、关于这个项目的任何其它信息也一律不许用。
2. 不要去调用文件里描述的那些工具(你也调不了)。你要做的是: 写出如果你是这个 agent, 你会依次发出的工具调用。每个调用给出工具名(tool)和完整、逐字可发送的 JSON 参数(args_json, 一个 JSON 对象的字符串, 包含 schema 要求的每个必填字段)。
3. 后面的调用如果依赖前面调用的返回: 行 id 写成以 "f_" 开头的占位字符串(例如 "f_weight_of_AAPL"), scenario 新建的 book 用以 "calc_" 开头的占位字符串; 其它依赖值(例如"最大持仓的 ticker")在 JSON 里写一个你认为合理的示例值。并在 depends_on 里说明它来自哪一步的什么结果。同一种调用如果要对多个对象各做一次, 只写出其中一次, 并在 repeat 里写次数和原因。
4. 写到你认为可以回答用户为止, 然后在 answer_shape 里说明你会怎么回答(结构和要点, 不要编数字)。
5. 如实标注: 每个调用的 certainty 写 certain / likely / guess(按所写原样会不会被接受), basis 写你是从 context 的哪里知道该这么调的(哪一段、哪句话或哪个 schema 字段)。
6. 最重要的一项: 在 unclear 里逐条列出 context 里缺的或不清楚的东西——凡是让你不得不猜、让你不确定某个参数该怎么写、或让你不确定桌子能不能做这件事的地方。没有就给空列表, 不要为了凑数编造; 有就写具体(哪个工具的哪个参数、哪句话有歧义、缺了什么信息)。
7. 如果按 context 判断桌子做不了用户要的某件事, 在 cannot 里写依据(引用 context 里的原话)以及你会怎么对用户说; 没有就写空字符串。
8. reading: 用一两句话写你对这道题需要知道什么的理解。
9. 最后把 read_only_the_given_files 如实填写: 只读了上面列出的文件填 true, 否则 false。

qid 用文件名里的题号(${pair.join('、')})。用中文写说明, 工具名和 JSON 保持原文。`
}

phase('Blind')
log(`7 个盲读 agent, 每个 2 题, 共 14 题`)
const results = await parallel(PAIRS.map(pair => () =>
  agent(promptFor(pair), { label: `blind:${pair.join('+')}`, phase: 'Blind', schema: SCHEMA, effort: 'high' })
    .then(r => ({ pair, result: r }))
))
const ok = results.filter(Boolean).filter(r => r.result)
const missing = PAIRS.filter(p => !ok.some(r => r.pair[0] === p[0])).map(p => p.join('+'))
if (missing.length) log(`未返回: ${missing.join(', ')}`)
return { answers: ok, missing }
