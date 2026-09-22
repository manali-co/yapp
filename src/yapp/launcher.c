/* Yapp.app main executable. Stays alive as the process macOS holds responsible for
   permissions (Microphone, Input Monitoring, Accessibility) and runs the Python app as a
   child, the way Terminal's grants cover the programs it runs. Rebuilt by `yapp install-app`. */
#include <mach-o/dyld.h>
#include <limits.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

int main(int argc, char **argv) {
    char exe[PATH_MAX];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0) return 2;
    char resolved[PATH_MAX];
    if (realpath(exe, resolved) == NULL) return 2;
    /* .../Yapp.app/Contents/MacOS/yapp -> .../Yapp.app/Contents/Resources/launch.sh */
    char *slash = strrchr(resolved, '/');
    if (slash) *slash = '\0';
    slash = strrchr(resolved, '/');
    if (slash) *slash = '\0';
    char script[PATH_MAX];
    snprintf(script, sizeof script, "%s/Resources/launch.sh", resolved);
    char *args[] = {"/bin/zsh", script, NULL};
    pid_t pid;
    if (posix_spawn(&pid, "/bin/zsh", NULL, NULL, args, environ) != 0) return 3;
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
