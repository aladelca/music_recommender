alter type public.recommendation_status
    add value if not exists 'degraded' after 'ready';

alter type public.recommendation_status
    add value if not exists 'insufficient' after 'degraded';
