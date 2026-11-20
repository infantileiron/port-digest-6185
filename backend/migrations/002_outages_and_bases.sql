--
-- 002: 停运登记与分站依据锁定
-- 依据表在单站首次开算/发报时冻结，之后补录不改变已锁定的 payload。
--

CREATE TABLE public.outages (
    id integer NOT NULL,
    station character varying(30) NOT NULL,
    started_at character varying(40) NOT NULL,
    ended_at character varying(40) NOT NULL,
    note text,
    created_by character varying(100),
    created_at character varying(40),
    updated_at character varying(40)
);

CREATE SEQUENCE public.outages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.outages_id_seq OWNED BY public.outages.id;
ALTER TABLE ONLY public.outages ALTER COLUMN id SET DEFAULT nextval('public.outages_id_seq'::regclass);
ALTER TABLE ONLY public.outages ADD CONSTRAINT outages_pkey PRIMARY KEY (id);

CREATE TABLE public.report_bases (
    id integer NOT NULL,
    report_day character varying(10) NOT NULL,
    station character varying(30) NOT NULL,
    created_at character varying(40),
    created_by character varying(100),
    checksum character varying(64),
    payload json
);

CREATE SEQUENCE public.report_bases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.report_bases_id_seq OWNED BY public.report_bases.id;
ALTER TABLE ONLY public.report_bases ALTER COLUMN id SET DEFAULT nextval('public.report_bases_id_seq'::regclass);
ALTER TABLE ONLY public.report_bases ADD CONSTRAINT report_bases_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.report_bases
    ADD CONSTRAINT uq_report_basis_day_station UNIQUE (report_day, station);
