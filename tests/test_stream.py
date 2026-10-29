import io
import threading
import unittest
from speech.jobs import Jobs, JobError
from speech.stream import pack, read_frame


class StreamTests(unittest.TestCase):
    def test_partial_reads_and_truncation(self):
        class Tiny(io.BytesIO):
            def read(self,n=-1):return super().read(min(n,2))
        blob=pack({'type':'audio'},b'1234')
        self.assertEqual(read_frame(Tiny(blob))[1],b'1234')
        for data in [blob[:-1],b'\xff'*4]:
            with self.assertRaises(ValueError):read_frame(io.BytesIO(data))

    def test_cancel_after_first_frame_prevents_late_commit(self):
        sent=threading.Event();release=threading.Event()
        def execute(job):
            jobs.publish(job,{'type':'audio'},b'12');sent.set();release.wait(2)
            jobs.commit(job,b'wav',{})
        jobs=Jobs(execute)
        try:
            job=jobs.submit({'client_id':'test','request_id':'1','stream':True},lambda p:{})
            self.assertTrue(sent.wait(1))
            self.assertEqual(jobs.get(job['id'])['state'],'streaming')
            frame,_,terminal=jobs.stream_next(job['id'],'test',0)
            self.assertFalse(terminal);self.assertIsNotNone(frame)
            jobs.cancel(job['id']);release.set()
            self.assertEqual(jobs.stream_next(job['id'],'test',1)[1]['state'],'cancelled')
            with self.assertRaises(JobError):jobs.audio(job['id'])
        finally:release.set();jobs.close()

    def test_buffer_limit(self):
        jobs=Jobs(lambda job:None)
        try:
            job={'state':'streaming'}
            for _ in range(512):jobs.publish(job,{'type':'audio'},b'12')
            with self.assertRaises(ValueError):jobs.publish(job,{'type':'audio'},b'12')
        finally:jobs.close()
