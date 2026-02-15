from abc import ABC, abstractmethod
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BaseJob(ABC):
    def __init__(self):
        pass

    @abstractmethod
    async def run(self, **kwargs):
        """
        Execute the job logic.
        """
        pass
