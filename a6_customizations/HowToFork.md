## 设置fork
fork qlib开源项目，在本地保持一些文件的修改，同时能够方便地拉取开源项目的云端更新。以下是AI助手关于这次操作的回答

**思路:**

核心思路是利用 Git 的分支（Branching）和远程仓库（Remotes）功能。

1.  **区分来源:** 你需要让本地的 Git 仓库知道两个远程仓库：一个是原始的开源项目仓库（我们通常称之为 `upstream`），另一个是你可能在 GitHub/GitLab 上创建的你自己的副本（fork，通常称为 `origin`，如果你 fork 了的话；如果直接 clone，`origin` 就指向原始仓库）。
2.  **隔离修改:** 你不应该直接在主分支（如 `main` 或 `master`）上进行你的修改。你应该创建一个属于你自己的新分支，专门用来存放你的定制化代码（包括新增的文件和对原有文件的修改）。
3.  **同步更新:** 当原始项目更新时，你需要先将这些更新拉取到你的本地主分支，然后再将这些更新合并（merge）或变基（rebase）到你自己的开发分支上。这样，你的分支就既包含了原始项目的最新代码，也包含了你自己的修改。

**具体步骤:**

假设原始开源项目的 GitHub URL 是 `https://github.com/original/repo.git`。

1.  **克隆仓库:**
    首先，将原始仓库克隆到你的本地。
    ```bash
    git clone https://github.com/original/repo.git
    cd repo
    ```
    现在，你的本地仓库有一个默认的远程仓库 `origin`，它指向 `https://github.com/original/repo.git`。

2.  **（可选但推荐）添加上游仓库:**
    虽然现在 `origin` 就指向原始仓库，但如果你打算 fork 这个项目到你自己的 GitHub 账号下，并把你的修改推送到你自己的 fork 上，那么标准的做法是：
    *   先在 GitHub 上 fork 原始仓库到你的账号（比如你的账号是 `your-username`，fork 后的地址是 `https://github.com/your-username/repo.git`）。
    *   然后克隆你自己的 fork：
        ```bash
        git clone https://github.com/your-username/repo.git
        cd repo
        ```
        这时 `origin` 指向你的 fork。
    *   添加原始仓库作为 `upstream`：
        ```bash
        git remote add upstream https://github.com/original/repo.git
        ```
    *   验证远程仓库设置：
        ```bash
        git remote -v
        ```
        你应该能看到 `origin` 指向你的 fork，`upstream` 指向原始仓库。

    *   **如果你不打算 fork，只是在本地修改**，那么第一步克隆后，`origin` 就已经是原始仓库了。为了清晰起见，你可以选择性地将其重命名为 `upstream`，或者就保留 `origin` 并记住它代表原始仓库。为与标准实践一致，我们假设你添加了 `upstream` 指向原始仓库。如果没 fork，后续步骤中将 `upstream` 替换为 `origin` 即可。

3.  **创建你的开发分支:**
    在进行任何修改之前，基于最新的主分支（通常是 `main` 或 `master`）创建一个新的分支来存放你的代码。假设原始项目的主分支是 `main`。
    ```bash
    # 确保你在最新的主分支上
    git checkout main
    git pull upstream main # 从原始仓库拉取最新代码到本地 main 分支

    # 创建并切换到你的新分支，例如命名为 my-customizations
    git checkout -b my-customizations
    ```
    现在你就在 `my-customizations` 分支上了，可以开始修改代码。

4.  **进行你的修改:**
    在这个 `my-customizations` 分支上，你可以自由地：
    *   创建新的 `.py` 文件或目录。
    *   修改现有的文件。
    *   删除文件。
    进行修改后，像平常一样提交你的更改：
    ```bash
    git add . # 或者 git add <specific_file>
    git commit -m "Add my custom feature X"
    ```
    你的所有修改都保存在 `my-customizations` 分支上，不会影响 `main` 分支。

5.  **同步上游更新:**
    当你想获取原始项目 (`upstream`) 的最新更新时，执行以下操作：
    *   **a. 获取上游更新:**
        ```bash
        git fetch upstream
        ```
        这会将 `upstream` 仓库的最新数据下载到你本地，但**不会**自动合并到你的任何分支。最新的 `main` 分支现在在你本地表示为 `upstream/main`。

    *   **b. 更新你的主分支 (可选但推荐):**
        为了保持本地 `main` 分支与 `upstream/main` 同步，可以这样做：
        ```bash
        git checkout main
        git merge upstream/main # 或者 git pull upstream main (等同于 fetch + merge)
        # 如果 main 分支只用于跟踪 upstream，更简洁的方式是：
        # git reset --hard upstream/main
        ```

    *   **c. 将更新整合到你的开发分支:**
        切换回你的开发分支：
        ```bash
        git checkout my-customizations
        ```
        现在，你有两种主要方式将 `upstream/main` 的更新整合进来：
        *   **Rebase (推荐):** 变基会把你当前分支 (`my-customizations`) 的提交“重新播放”到 `upstream/main` 的最新提交之上。这会使你的提交历史更线性、更清晰。
            ```bash
            git rebase upstream/main
            ```
        *   **Merge:** 合并会在你的 `my-customizations` 分支上创建一个新的合并提交，将 `upstream/main` 的历史合并进来。
            ```bash
            git merge upstream/main
            ```

        **选择 Rebase 还是 Merge?**
        *   `rebase` 使历史更整洁，看起来就像你的修改是基于最新版开发的。
        *   `merge` 保留了更精确的历史记录（包括合并点），但可能使历史图谱更复杂。
        *   对于保持个人开发分支与上游同步的场景，`rebase` 通常是更好的选择。

    *   **d. 处理冲突:**
        无论使用 `rebase` 还是 `merge`，如果你的修改和上游的更新修改了同一个文件的同一部分，就会发生冲突（Conflict）。Git 会提示你哪些文件有冲突。
        *   你需要手动编辑这些文件，解决冲突（删除 Git 添加的冲突标记 `<<<<<<<`, `=======`, `>>>>>>>`，并决定最终的代码）。
        *   解决冲突后：
            *   如果用的是 `rebase`：`git add <resolved_file>`，然后 `git rebase --continue`。重复此过程直到 rebase 完成。如果想中途放弃，用 `git rebase --abort`。
            *   如果用的是 `merge`：`git add <resolved_file>`，然后 `git commit` 来完成合并提交。

**总结:**

通过这种方式：

*   你的 `main` 分支（或者你选择用来跟踪原始仓库的分支）可以随时通过 `git pull upstream main` 或 `git fetch upstream` + `git merge upstream/main` 来保持与原始项目同步。
*   你的所有定制化修改都在 `my-customizations` 分支上，与 `main` 分支隔离。
*   当你执行 `git rebase upstream/main` (或 `merge`) 时，原始项目的更新会被整合到你的 `my-customizations` 分支，同时 Git 会尝试保留你在该分支上所做的所有提交（包括你新增的文件和对文件的修改）。
*   只要你的修改和上游更新没有直接冲突，这个过程通常很顺利。即使有冲突，Git 也会指导你手动解决。

这样就实现了你的目标：既能跟上原始项目的更新，又能保留自己的定制化代码。