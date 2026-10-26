--
-- PostgreSQL database dump
--


-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alerta; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alerta (
    id uuid NOT NULL,
    tramite_id uuid NOT NULL,
    observacion_id uuid,
    dias_previos integer NOT NULL,
    fecha_programada date NOT NULL,
    enviada boolean,
    enviada_en timestamp with time zone,
    canal character varying(20),
    creado_en timestamp with time zone
);


--
-- Name: auditoria_tramite; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auditoria_tramite (
    id uuid NOT NULL,
    tramite_id uuid NOT NULL,
    empresa_id uuid,
    empresa_nombre text,
    tramite_nombre text,
    usuario_id uuid,
    campo character varying(50) NOT NULL,
    valor_anterior text,
    valor_nuevo text,
    creado_en timestamp with time zone
);


--
-- Name: documento; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documento (
    id uuid NOT NULL,
    tramite_id uuid NOT NULL,
    observacion_id uuid,
    tipo character varying(30) NOT NULL,
    nombre_archivo text NOT NULL,
    clave_almacenamiento text NOT NULL,
    tamano_bytes integer,
    version integer NOT NULL,
    subido_por_id uuid,
    creado_en timestamp with time zone,
    CONSTRAINT documento_tipo_valido CHECK (((tipo)::text = ANY ((ARRAY['ingreso'::character varying, 'resolucion'::character varying, 'observacion'::character varying, 'otro'::character varying])::text[])))
);


--
-- Name: empresa_cliente; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.empresa_cliente (
    id uuid NOT NULL,
    organizacion_id uuid NOT NULL,
    nombre character varying(250) NOT NULL,
    nit character varying(30),
    contacto_nombre character varying(150),
    contacto_email character varying(200),
    contacto_telefono character varying(30),
    notas text,
    creado_en timestamp with time zone
);


--
-- Name: intento_login; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.intento_login (
    id uuid NOT NULL,
    email_intentado character varying(200) NOT NULL,
    ip character varying(64),
    exitoso boolean NOT NULL,
    creado_en timestamp with time zone
);


--
-- Name: observacion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.observacion (
    id uuid NOT NULL,
    tramite_id uuid NOT NULL,
    numero integer NOT NULL,
    fecha_emision date,
    motivo text,
    fecha_vencimiento date,
    fecha_respuesta date,
    creado_en timestamp with time zone
);


--
-- Name: organizacion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizacion (
    id uuid NOT NULL,
    nombre character varying(200) NOT NULL,
    creado_en timestamp with time zone
);


--
-- Name: tipo_tramite; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tipo_tramite (
    id uuid NOT NULL,
    categoria character varying(50) NOT NULL,
    nombre character varying(250) NOT NULL,
    institucion character varying(100),
    tipo_gestion character varying(100),
    vigencia_meses integer,
    vigencia_desde character varying(10),
    etapas json,
    es_recurrente boolean,
    frecuencia_dias integer,
    checklist_default json,
    notas text,
    activo boolean
);


--
-- Name: tramite; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tramite (
    id uuid NOT NULL,
    empresa_cliente_id uuid NOT NULL,
    tipo_tramite_id uuid NOT NULL,
    asignado_a uuid,
    creado_por_id uuid,
    numero_expediente character varying(100),
    fecha_inicio date NOT NULL,
    fecha_vencimiento date,
    estado character varying(20),
    checklist json,
    notas text,
    resolucion_final character varying(20),
    fecha_aprobacion date,
    etapas_fechas json,
    descripcion text,
    numero_registro character varying(100),
    anticipo text,
    complemento text,
    creado_en timestamp with time zone,
    actualizado_en timestamp with time zone,
    CONSTRAINT tramite_estado_check CHECK (((estado)::text = ANY ((ARRAY['en_tramite'::character varying, 'vigente'::character varying, 'por_vencer'::character varying, 'vencido'::character varying, 'renovacion_en_curso'::character varying])::text[])))
);


--
-- Name: usuario; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usuario (
    id uuid NOT NULL,
    organizacion_id uuid NOT NULL,
    nombre character varying(150) NOT NULL,
    email character varying(200) NOT NULL,
    password_hash character varying(255) NOT NULL,
    rol character varying(20) NOT NULL,
    activo boolean,
    creado_en timestamp with time zone,
    CONSTRAINT usuario_rol_check CHECK (((rol)::text = ANY ((ARRAY['admin'::character varying, 'gestor'::character varying])::text[])))
);


--
-- Name: usuario_empresa_cliente; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usuario_empresa_cliente (
    usuario_id uuid NOT NULL,
    empresa_cliente_id uuid NOT NULL
);


--
-- Name: alerta alerta_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerta
    ADD CONSTRAINT alerta_pkey PRIMARY KEY (id);


--
-- Name: auditoria_tramite auditoria_tramite_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auditoria_tramite
    ADD CONSTRAINT auditoria_tramite_pkey PRIMARY KEY (id);


--
-- Name: documento documento_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documento
    ADD CONSTRAINT documento_pkey PRIMARY KEY (id);


--
-- Name: empresa_cliente empresa_cliente_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.empresa_cliente
    ADD CONSTRAINT empresa_cliente_pkey PRIMARY KEY (id);


--
-- Name: intento_login intento_login_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.intento_login
    ADD CONSTRAINT intento_login_pkey PRIMARY KEY (id);


--
-- Name: observacion observacion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observacion
    ADD CONSTRAINT observacion_pkey PRIMARY KEY (id);


--
-- Name: organizacion organizacion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizacion
    ADD CONSTRAINT organizacion_pkey PRIMARY KEY (id);


--
-- Name: tipo_tramite tipo_tramite_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tipo_tramite
    ADD CONSTRAINT tipo_tramite_pkey PRIMARY KEY (id);


--
-- Name: tramite tramite_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tramite
    ADD CONSTRAINT tramite_pkey PRIMARY KEY (id);


--
-- Name: usuario usuario_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuario
    ADD CONSTRAINT usuario_email_key UNIQUE (email);


--
-- Name: usuario_empresa_cliente usuario_empresa_cliente_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuario_empresa_cliente
    ADD CONSTRAINT usuario_empresa_cliente_pkey PRIMARY KEY (usuario_id, empresa_cliente_id);


--
-- Name: usuario usuario_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuario
    ADD CONSTRAINT usuario_pkey PRIMARY KEY (id);


--
-- Name: alerta alerta_observacion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerta
    ADD CONSTRAINT alerta_observacion_id_fkey FOREIGN KEY (observacion_id) REFERENCES public.observacion(id) ON DELETE CASCADE;


--
-- Name: alerta alerta_tramite_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerta
    ADD CONSTRAINT alerta_tramite_id_fkey FOREIGN KEY (tramite_id) REFERENCES public.tramite(id);


--
-- Name: auditoria_tramite auditoria_tramite_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auditoria_tramite
    ADD CONSTRAINT auditoria_tramite_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuario(id);


--
-- Name: documento documento_observacion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documento
    ADD CONSTRAINT documento_observacion_id_fkey FOREIGN KEY (observacion_id) REFERENCES public.observacion(id) ON DELETE CASCADE;


--
-- Name: documento documento_subido_por_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documento
    ADD CONSTRAINT documento_subido_por_id_fkey FOREIGN KEY (subido_por_id) REFERENCES public.usuario(id);


--
-- Name: documento documento_tramite_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documento
    ADD CONSTRAINT documento_tramite_id_fkey FOREIGN KEY (tramite_id) REFERENCES public.tramite(id) ON DELETE CASCADE;


--
-- Name: empresa_cliente empresa_cliente_organizacion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.empresa_cliente
    ADD CONSTRAINT empresa_cliente_organizacion_id_fkey FOREIGN KEY (organizacion_id) REFERENCES public.organizacion(id);


--
-- Name: observacion observacion_tramite_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observacion
    ADD CONSTRAINT observacion_tramite_id_fkey FOREIGN KEY (tramite_id) REFERENCES public.tramite(id) ON DELETE CASCADE;


--
-- Name: tramite tramite_asignado_a_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tramite
    ADD CONSTRAINT tramite_asignado_a_fkey FOREIGN KEY (asignado_a) REFERENCES public.usuario(id);


--
-- Name: tramite tramite_creado_por_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tramite
    ADD CONSTRAINT tramite_creado_por_id_fkey FOREIGN KEY (creado_por_id) REFERENCES public.usuario(id);


--
-- Name: tramite tramite_empresa_cliente_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tramite
    ADD CONSTRAINT tramite_empresa_cliente_id_fkey FOREIGN KEY (empresa_cliente_id) REFERENCES public.empresa_cliente(id);


--
-- Name: tramite tramite_tipo_tramite_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tramite
    ADD CONSTRAINT tramite_tipo_tramite_id_fkey FOREIGN KEY (tipo_tramite_id) REFERENCES public.tipo_tramite(id);


--
-- Name: usuario_empresa_cliente usuario_empresa_cliente_empresa_cliente_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuario_empresa_cliente
    ADD CONSTRAINT usuario_empresa_cliente_empresa_cliente_id_fkey FOREIGN KEY (empresa_cliente_id) REFERENCES public.empresa_cliente(id);


--
-- Name: usuario_empresa_cliente usuario_empresa_cliente_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuario_empresa_cliente
    ADD CONSTRAINT usuario_empresa_cliente_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuario(id);


--
-- Name: usuario usuario_organizacion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usuario
    ADD CONSTRAINT usuario_organizacion_id_fkey FOREIGN KEY (organizacion_id) REFERENCES public.organizacion(id);


--
-- PostgreSQL database dump complete
--


