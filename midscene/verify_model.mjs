import 'dotenv/config';
import { agentFromAdbDevice, getConnectedDevices } from '@midscene/android';
const devices = await getConnectedDevices();
if (!devices.length) throw new Error('No Android devices found');
const agent = await agentFromAdbDevice(devices[0].udid);
await agent.aiAssert('The current screen shows the 王者荣耀 game main menu and is not inside a match.');
console.log('VISUAL_ASSERT_OK device=' + devices[0].udid);
