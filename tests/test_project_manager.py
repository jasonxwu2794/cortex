"""Tests for ProjectManager, GitOps, and related components."""

import os
import tempfile
import unittest

from agents.brain.project_manager import ProjectManager, Task, Project


class TestProjectManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test_projects.db")
        self.pm = ProjectManager(db_path=self.db_path)

    def test_create_project(self):
        proj = self.pm.create_project("Test App", "A test application", "# Spec\n...")
        self.assertIsInstance(proj, Project)
        self.assertEqual(proj.name, "Test App")
        self.assertEqual(proj.status, "planning")

    def test_get_active_project(self):
        self.assertIsNone(self.pm.get_active_project())
        proj = self.pm.create_project("Test", "desc", "spec")
        active = self.pm.get_active_project()
        self.assertIsNotNone(active)
        self.assertEqual(active.id, proj.id)

    def test_single_active_project_limit(self):
        self.pm.create_project("P1", "d1", "s1")
        with self.assertRaises(ValueError):
            self.pm.create_project("P2", "d2", "s2")

    def test_detect_project(self):
        self.assertTrue(self.pm.detect_project("I want to build a web app with authentication and database"))
        self.assertTrue(self.pm.detect_project("Let's create a tool that has multiple features"))
        self.assertFalse(self.pm.detect_project("hello"))
        self.assertFalse(self.pm.detect_project("what's the weather?"))

    def test_decompose_and_complete_tasks(self):
        proj = self.pm.create_project("Test", "desc", "spec")
        tasks = [
            Task(id="t1", project_id=proj.id, title="Design", description="Design DB", agent="builder", depends_on=[], order=1),
            Task(id="t2", project_id=proj.id, title="Build", description="Build API", agent="builder", depends_on=["t1"], order=2),
            Task(id="t3", project_id=proj.id, title="Test", description="Test it", agent="verifier", depends_on=["t2"], order=3),
        ]
        self.pm.decompose_into_tasks(proj.id, tasks)

        # Project should be in_progress now
        active = self.pm.get_active_project()
        self.assertEqual(active.status, "in_progress")

        # Next task should be t1 (no deps)
        next_t = self.pm.get_next_task(proj.id)
        self.assertEqual(next_t.id, "t1")

        # Complete t1
        self.pm.complete_task("t1", "Done designing")
        next_t = self.pm.get_next_task(proj.id)
        self.assertEqual(next_t.id, "t2")

        # Complete t2
        self.pm.complete_task("t2", "API built")
        next_t = self.pm.get_next_task(proj.id)
        self.assertEqual(next_t.id, "t3")

        # Complete t3 → project should auto-complete
        self.pm.complete_task("t3", "All tests pass")
        active = self.pm.get_active_project()
        self.assertIsNone(active)  # No active project (it's completed)

    def test_get_status(self):
        proj = self.pm.create_project("Test", "desc", "spec")
        tasks = [
            Task(id="t1", project_id=proj.id, title="Task 1", description="d", agent="builder", order=1),
            Task(id="t2", project_id=proj.id, title="Task 2", description="d", agent="builder", depends_on=["t1"], order=2),
        ]
        self.pm.decompose_into_tasks(proj.id, tasks)

        status = self.pm.get_status(proj.id)
        self.assertEqual(status.total_tasks, 2)
        self.assertEqual(status.completed_tasks, 0)

        self.pm.complete_task("t1", "done")
        status = self.pm.get_status(proj.id)
        self.assertEqual(status.completed_tasks, 1)
        self.assertAlmostEqual(status.progress_pct, 50.0)

    def test_pause_and_resume(self):
        proj = self.pm.create_project("Test", "desc", "spec")
        self.pm.update_project_status(proj.id, "paused")
        self.assertIsNone(self.pm.get_active_project())

        # Can create new project after pausing
        proj2 = self.pm.create_project("P2", "d2", "s2")
        self.assertIsNotNone(proj2)


class TestGitOps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        from agents.common.gitops import GitOps
        self.gitops = GitOps(self.tmp)

    def test_init_repo(self):
        self.assertTrue(self.gitops.init_repo())
        self.assertTrue(os.path.exists(os.path.join(self.tmp, ".git")))
        # Second call should also succeed
        self.assertTrue(self.gitops.init_repo())

    def test_auto_commit(self):
        self.gitops.init_repo()
        # Configure git for tests
        os.system(f'cd {self.tmp} && git config user.email "test@test.com" && git config user.name "Test"')

        # Write a file and commit
        with open(os.path.join(self.tmp, "test.py"), "w") as f:
            f.write("print('hello')\n")

        commit_hash = self.gitops.auto_commit("Initial test commit")
        self.assertIsNotNone(commit_hash)
        self.assertTrue(len(commit_hash) > 0)

    def test_auto_commit_nothing(self):
        self.gitops.init_repo()
        os.system(f'cd {self.tmp} && git config user.email "test@test.com" && git config user.name "Test"')
        # Create initial commit so repo isn't empty
        with open(os.path.join(self.tmp, "init.txt"), "w") as f:
            f.write("init")
        self.gitops.auto_commit("init")
        # Now nothing to commit
        result = self.gitops.auto_commit("Empty commit")
        self.assertIsNone(result)

    def test_pre_commit_check_secrets(self):
        self.gitops.init_repo()
        os.system(f'cd {self.tmp} && git config user.email "test@test.com" && git config user.name "Test"')
        # Write a file with a fake secret and stage it
        with open(os.path.join(self.tmp, "config.py"), "w") as f:
            f.write('API_KEY = "sk-abcdefghijklmnopqrstuvwxyz1234567890"\n')
        os.system(f'cd {self.tmp} && git add config.py')

        warnings = self.gitops.pre_commit_check()
        self.assertTrue(len(warnings) > 0)
        self.assertTrue(any("OpenAI" in w or "secret" in w.lower() for w in warnings))

    def test_pre_commit_check_env_file(self):
        self.gitops.init_repo()
        os.system(f'cd {self.tmp} && git config user.email "test@test.com" && git config user.name "Test"')
        with open(os.path.join(self.tmp, ".env"), "w") as f:
            f.write("SECRET=foo\n")
        os.system(f'cd {self.tmp} && git add -f .env')

        warnings = self.gitops.pre_commit_check()
        self.assertTrue(any(".env" in w for w in warnings))

    def test_get_status(self):
        self.gitops.init_repo()
        status = self.gitops.get_status()
        self.assertIn("branch", status)

    def test_get_log(self):
        self.gitops.init_repo()
        os.system(f'cd {self.tmp} && git config user.email "test@test.com" && git config user.name "Test"')
        with open(os.path.join(self.tmp, "f.txt"), "w") as f:
            f.write("x")
        self.gitops.auto_commit("test log")
        log = self.gitops.get_log()
        self.assertTrue(len(log) > 0)
        self.assertEqual(log[0]["message"], "test log")

    def test_rollback(self):
        self.gitops.init_repo()
        os.system(f'cd {self.tmp} && git config user.email "test@test.com" && git config user.name "Test"')

        with open(os.path.join(self.tmp, "a.txt"), "w") as f:
            f.write("v1")
        self.gitops.auto_commit("v1")

        with open(os.path.join(self.tmp, "a.txt"), "w") as f:
            f.write("v2")
        self.gitops.auto_commit("v2")

        self.assertTrue(self.gitops.rollback())


if __name__ == "__main__":
    unittest.main()
