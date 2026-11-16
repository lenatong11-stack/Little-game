import 'dotenv/config';
import { agentFromAdbDevice } from '@midscene/android';
import { execFile } from 'node:child_process';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';

const execAdb = promisify(execFile);
const emit = (type, message, fields = {}) =>
  process.stdout.write(JSON.stringify({ type, message, ...fields }) + '\n');
const context = [
  '按当前用户指令操作目标应用，每次根据最新截图确定控件和状态。',
  '遇到启动动画或读条时先等待并检查新画面，不能把加载画面判为完成。',
  '只执行指令所需的操作。需要密码、扫码、验证码或第三方账号授权时，报告原因并停止。',
  '不要执行 ADB Shell，不要猜坐标。遇到意外页面或找不到控件时明确报告失败。',
  '只有截图确认用户要求的可见结果已经出现，才能报告步骤完成。',
].join('\n');

let input;
let agent;

async function capture(label) {
  const file = label + '.png';
  const { stdout } = await execAdb(input.adb, [
    '-s', input.serial, 'exec-out', 'screencap', '-p',
  ], { encoding: 'buffer', maxBuffer: 32 * 1024 * 1024, timeout: 12000, windowsHide: true });
  if (stdout.length < 24 || !stdout.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))) {
    throw new Error('设备没有返回有效的 PNG 截图');
  }
  await writeFile(join(input.folder, file), stdout);
  emit('screenshot', '已保存截图：' + file, { file });
}

try {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  input = JSON.parse(raw);
  const steps = input.goal.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (!steps.length || steps.length > 20) throw new Error('请填写 1 至 20 行自然语言步骤');
  if (!process.env.MIDSCENE_MODEL_API_KEY) throw new Error('请先在 midscene/.env 配置视觉模型');
  agent = await agentFromAdbDevice(input.serial, {
    replanningCycleLimit: 15,
    aiContexts: { aiAct: context },
    onTaskStartTip: tip => emit('progress', String(tip)),
  });

  emit('stage', '启动目标应用：' + input.package, { stage: 0 });
  await agent.launch(input.package);
  await agent.aiWaitFor('目标应用的实际界面已经显示并可交互，当前不是手机桌面、黑屏、启动标志或加载画面。若有应用内的登录入口或首页即可。', {
    timeoutMs: 240000,
    checkIntervalMs: 6000,
  });
  await capture('stage-0');

  for (const [index, step] of steps.entries()) {
    const stage = index + 1;
    emit('stage', '第 ' + stage + ' 步：' + step, { stage });
    await agent.aiAct(step, { cacheable: false });
    await capture('stage-' + stage);
  }
  if (input.assertion?.trim()) {
    const stage = steps.length + 1;
    emit('stage', '检查最终结果：' + input.assertion, { stage });
    await agent.aiWaitFor(input.assertion, { timeoutMs: 180000, checkIntervalMs: 6000 });
    await capture('stage-' + stage);
  }
  emit('success', input.assertion?.trim()
    ? '自然语言步骤已执行，最终视觉条件通过。'
    : 'Midscene 已报告所有步骤完成，请结合截图核对结果。');
} catch (error) {
  emit('error', error?.message || String(error));
  if (input?.serial) {
    try { await capture('failure'); }
    catch (captureError) { emit('progress', '无法保存现场截图：' + captureError.message); }
  }
  process.exitCode = 1;
} finally {
  if (agent) await agent.destroy().catch(() => {});
}
