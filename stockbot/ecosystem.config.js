// PM2 process manager config for 24/7 VPS operation.
//
//   npm install -g pm2
//   pm2 start ecosystem.config.js
//   pm2 save && pm2 startup      # auto-restart on reboot
//   pm2 logs trading-bot
//
// Assumes a virtualenv at ./.venv (see README). Adjust `interpreter` if needed.
module.exports = {
  apps: [
    {
      name: "trading-bot",
      script: "-m bot.main",
      interpreter: "./.venv/bin/python",
      cwd: __dirname,
      autorestart: true,
      restart_delay: 10000,
      max_restarts: 50,
      time: true,
      out_file: "logs/bot.out.log",
      error_file: "logs/bot.err.log",
    },
    // Optional: run briefings on a schedule via PM2 cron (in addition to Cowork).
    {
      name: "briefing-morning",
      script: "-m bot.briefing morning",
      interpreter: "./.venv/bin/python",
      cwd: __dirname,
      autorestart: false,
      cron_restart: "0 7 * * *",
      time: true,
    },
    {
      name: "briefing-evening",
      script: "-m bot.briefing evening",
      interpreter: "./.venv/bin/python",
      cwd: __dirname,
      autorestart: false,
      cron_restart: "0 21 * * *",
      time: true,
    },
  ],
};
