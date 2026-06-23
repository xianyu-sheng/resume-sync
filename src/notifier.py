"""
Windows Toast notification via PowerShell.

Sends native Windows 10/11 toast notifications for resume-sync events.
No third-party libraries required.
"""

import subprocess
import textwrap


def _escape_ps(s: str) -> str:
    """Escape a string for embedding in PowerShell double-quoted string."""
    return s.replace('"', '`"').replace('$', '`$')


def _send_toast(title: str, body: str) -> bool:
    """
    Send a Windows Toast notification using PowerShell.
    Returns True if the notification was sent successfully.
    """
    title_esc = _escape_ps(title)
    body_esc = _escape_ps(body)

    ps_script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $template.GetElementsByTagName("text")
$texts[0].AppendChild($template.CreateTextNode("{title_esc}")) | Out-Null
$texts[1].AppendChild($template.CreateTextNode("{body_esc}")) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Resume-Sync")
$notifier.Show($toast)
'''

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def notify(title: str, body: str) -> bool:
    """
    Send a resume-sync notification.

    Args:
        title: Short title line
        body: One-line description

    Returns:
        True if notification was sent successfully.

    Usage:
        notify("🔔 MyProject 有更新", "发现 3 个新提交，请运行 resume-sync plan")
        notify("✅ 简历已编译", "PDF 已保存到 /path/to/resume.pdf")
    """
    return _send_toast(title, body)


def notify_changes(project_name: str, commit_count: int) -> bool:
    """Standard notification for detected changes."""
    return notify(
        f"\U0001F514 {project_name} 有更新",
        f"发现 {commit_count} 个新提交，请运行 resume-sync plan 查看更新建议"
    )


def notify_build_success(pdf_path: str) -> bool:
    """Standard notification for successful build."""
    return notify(
        "✅ 简历已编译",
        f"PDF 已保存到 {pdf_path}"
    )


def notify_build_failure(error_count: int) -> bool:
    """Standard notification for build failure."""
    return notify(
        "❌ 简历编译失败",
        f"发现 {error_count} 个错误，请检查 main.tex"
    )
