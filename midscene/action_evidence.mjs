// Wrap the public DeviceAction.call interface before AndroidAgent is constructed.
// Screenshot errors are fatal: do not silently continue without required evidence.
export function withEvidence(actions, capture, getStage) {
  let sequence = 0;
  return actions.map(action => ({
    ...action,
    async call(...args) {
      const number = ++sequence;
      const prefix = `action-${String(number).padStart(4, '0')}`;
      const fields = { action: action.name, action_index: number, stage: getStage() };
      await capture(`${prefix}-before`, { ...fields, phase: 'before' });
      let value;
      try {
        value = await action.call.apply(action, args);
      } catch (error) {
        try { await capture(`${prefix}-failed`, { ...fields, phase: 'failed' }); }
        catch (captureError) { error.message += `；失败现场截图失败：${captureError.message}`; }
        throw error;
      }
      await new Promise(resolve => setTimeout(resolve, 300));
      await capture(`${prefix}-after`, { ...fields, phase: 'after' });
      return value;
    },
  }));
}
