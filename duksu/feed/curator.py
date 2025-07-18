import asyncio
from typing import List, Literal, Optional, Dict, Any, Tuple
from langchain.schema.language_model import BaseLanguageModel
from pydantic import BaseModel, Field

from duksu.feed.scorer import RelevanceScorer, Score
from duksu.news.model import NewsArticle
from duksu.feed.model import NewsCuration, NewsCurationItem
from duksu.logging_config import create_logger
from duksu.agent.prompts import AIPrompt, SystemPrompt


class CurationResult(BaseModel):
    selected_articles: List[str] = Field(description="URLs of articles selected for the feed")
    curation_summary: str = Field(description="Summary of the curation process and rationale")


class FeedCurator:
    """
    News article curator for intelligent article selection.
    """
    
    def __init__(self, llm: BaseLanguageModel, system_prompt: Optional[SystemPrompt] = None):
        self.llm = llm
        self.curator = llm.with_structured_output(CurationResult)
        self.system_prompt = system_prompt or SystemPrompt()
        self.logger = create_logger("FeedCurator")
        
        # Initialize the Scorers
        self.relevancy_scorer = RelevanceScorer(llm, system_prompt)
    
    def _filter_by_score(self, articles_with_scores: List[Tuple[NewsArticle, Score]], min_score: float) -> List[Tuple[NewsArticle, Score]]:
        return [article_with_score for article_with_score in articles_with_scores if article_with_score[1].score >= min_score]

    async def curate_news_feed(
        self,
        query_prompt: str,
        articles: List[NewsArticle],
        min_relevance_score: float,
        max_articles_per_batch: Optional[int] = None,        
    ) -> NewsCuration:
        """
        Curate a news feed from a list of articles based on a query prompt.
        """
        assert query_prompt.strip() != ""

        self.logger.info(f"Starting news curation job; query_prompt: \"{query_prompt[:100]}\"; considering {len(articles)} articles; articles per batch: {max_articles_per_batch}")

        try:
            relevant_articles: List[Tuple[NewsArticle, Score]] = []
            articles_batches = [articles] if max_articles_per_batch is None else [articles[i:i + max_articles_per_batch] for i in range(0, len(articles), max_articles_per_batch)]

            count = 0
            for batch in articles_batches:
                count += 1
                self.logger.debug(f"Scoring batch ({count}/{len(articles_batches)}) of {len(batch)} articles")
                
                scorer_response = self.relevancy_scorer.score_articles(batch, query_prompt)
                articles_with_scores = list(zip(batch, scorer_response.scores))

                # Filtering by score criteria
                relevant_articles_in_batch = self._filter_by_score(articles_with_scores, min_relevance_score)

                self.logger.debug(f"Found {len(relevant_articles_in_batch)} relevant articles in batch")

                relevant_articles.extend(relevant_articles_in_batch)
            
            if not relevant_articles:
                self.logger.warning("No articles met the minimum relevance criteria")
                return NewsCuration(
                    query_prompt=query_prompt,
                    items=[]
                )

            # Sort articles by relevance score in descending order
            relevant_articles.sort(key=lambda x: x[1].score, reverse=True)
            
            curation_items = []
            for article, relevance_score in relevant_articles:
                curation_items.append(NewsCurationItem(
                    item=article,
                    scores={
                        "relevance": {
                            "score": relevance_score.score,
                            "reasoning": relevance_score.reasoning
                        }
                    }
                ))
            
            return NewsCuration(
                query_prompt=query_prompt,
                items=curation_items
            )
            
        except Exception as e:
            self.logger.error(f"Error during curation: {e}")
            raise