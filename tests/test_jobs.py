import threading
import time
import unittest
from speech.jobs import Jobs, JobError


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.release=threading.Event();self.started=threading.Event()
        def execute(job):
            self.started.set();self.release.wait(3)
            self.jobs.commit(job,b"audio",{"X-Cached":"0"})
        self.jobs=Jobs(execute)
    def tearDown(self):
        self.release.set();self.jobs.close()
    def payload(self,index=1):return {"client_id":"tab","request_id":str(index),"text":"原文"}
    def submit(self,index=1):return self.jobs.submit(self.payload(index),lambda p:{"speech_text":p["text"]})
    def test_idempotency_precedes_new_snapshot(self):
        first=self.submit()
        second=self.jobs.submit(self.payload(),lambda p:(_ for _ in ()).throw(Exception("must not run")))
        self.assertEqual(first["id"],second["id"])
        with self.assertRaises(JobError):self.jobs.submit({**self.payload(),"text":"別文"},lambda p:{})
    def test_cancel_prevents_late_audio(self):
        job=self.submit();self.assertTrue(self.started.wait(1));self.jobs.cancel(job["id"]);self.release.set()
        with self.assertRaises(JobError):self.jobs.audio(job["id"])
        self.assertEqual(self.jobs.get(job["id"])["state"],"cancelled")
    def test_client_bound_and_cancel_isolation(self):
        values=[self.submit(i) for i in range(8)]
        with self.assertRaises(JobError) as exc:self.submit(9)
        self.assertEqual(exc.exception.status,429)
        self.jobs.cancel_client("other")
        self.assertEqual(self.jobs.get(values[-1]["id"])["state"],"queued")
        self.jobs.cancel_client("tab")
        self.assertEqual(self.jobs.get(values[-1]["id"])["state"],"cancelled")
    def test_snapshot_is_not_changed_by_caller(self):
        snapshot={"speech_text":"きょう"}
        job=self.jobs.submit(self.payload(),lambda p:snapshot)
        job["snapshot"]["speech_text"]="changed"
        self.assertEqual(self.jobs.get(job["id"])["snapshot"]["speech_text"],"きょう")

    def test_cancelled_backlog_is_bounded_and_does_not_kill_consumer(self):
        first=self.submit(0);self.assertTrue(self.started.wait(1))
        for i in range(1,225):
            job=self.submit(i);self.jobs.cancel(job["id"])
        self.assertLessEqual(len(self.jobs.items),201)
        final=self.submit(1000);self.release.set()
        for _ in range(100):
            state=self.jobs.get(final["id"])["state"]
            if state=="ready":break
            time.sleep(.01)
        self.assertEqual(state,"ready")


if __name__=="__main__":unittest.main()
