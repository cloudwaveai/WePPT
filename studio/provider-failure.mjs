// Only explicit terminal error lines are evidence; CLI stderr also echoes prompts.
export function providerFailure(log, exitCode) {
 const lines=String(log).replace(/\x1b\[[0-9;]*m/g,'').split(/\r?\n/);
 const terminal=lines.filter(line=>/^\s*(?:Error:|ERROR\b)/.test(line)).at(-1)||'';
 const status=Number(/\b(?:HTTP(?:\/\d(?:\.\d)?)?|status(?:\s+code)?)\s*[:=]?\s*(\d{3})\b/i.exec(terminal)?.[1])||null;
 let category='unknown';
 if(status===401||status===403||/\b(?:unauthorized|forbidden|authentication failed|invalid api key|token expired|please log in)\b/i.test(terminal))category='authorization';
 else if(/\b(?:insufficient_quota|quota exceeded|billing hard limit)\b/i.test(terminal))category='quota';
 else if(status===429||/\brate limit(?:ed| exceeded)?\b/i.test(terminal))category='rate_limit';
 else if([500,502,503,504].includes(status))category='provider_unavailable';
 else if(status===408||/\b(?:timed out|timeout)\b/i.test(terminal))category='timeout';
 else if(/\b(?:ECONNRESET|ECONNREFUSED|EAI_AGAIN|ENOTFOUND|fetch failed|connection reset|connection closed|stream disconnected)\b/i.test(terminal))category='network';
 else if(/model.*(?:not found|not supported|not available)|unsupported model/i.test(terminal))category='model_unavailable';
 const retryable=['rate_limit','provider_unavailable','network'].includes(category);
 const messages={authorization:'服务器 AI 服务认证失败，请联系管理员检查服务凭证。',quota:'AI 服务额度不足，请联系管理员。',model_unavailable:'服务器当前配置的模型不可用，请联系管理员。',rate_limit:'AI 服务暂时限流，请稍后继续生成。',provider_unavailable:'AI 服务暂时不可用，请稍后继续生成。',network:'AI 服务连接中断，请稍后继续生成。',timeout:'AI 设计响应超时，请稍后继续生成。'};
 const error=Error(messages[category]||'AI 设计调用失败，原稿已保留，可继续生成。');
 error.diagnostic={exitCode,status,category,retryable};
 if(status)error.status=status;
 return error;
}
