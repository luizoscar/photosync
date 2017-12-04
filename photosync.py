#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

import gi
import sys
import re
import os
import datetime
import time
import getopt
import logging
import math
import shutil
import subprocess

from lxml import etree as ET
from glob import glob
from threading import Thread
from distutils import spawn
from __builtin__ import str

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

from gi.repository import Gdk, Gtk, GObject, GLib


class VideoEncodeProgressDialog(Gtk.Dialog):
    """
    Dialog utilizada para exibir o progresso da conversão de vídeos
    """
    
    total = 0
    completed_size = 0
    must_stop = False
    failed = False

    def __init__(self, parent, arquivos, destino):
        Gtk.Dialog.__init__(self, "Compactando vídeos ", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL))

        self.set_size_request(250, 150)
        self.set_border_width(10)

        self.lista_arquivos = arquivos
        self.dir_destino = destino

        # Container principal
        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(4)
        grid.set_row_spacing(6)

        for arquivo in self.lista_arquivos:
            self.total = self.total + os.stat(arquivo).st_size

        # Label com o título da atividade
        grid.attach(Gtk.Label(label="Efetuando a re-codificação de " + str(len(arquivos)) + 
                              " arquivos (" + to_human_size(self.total) + ")", halign=Gtk.Align.START), 0, 0, 6, 1)

        # Progresso total
        self.progress_bar_total = Gtk.ProgressBar(show_text=True)
        grid.attach(self.progress_bar_total, 0, 1, 6, 1)

        # Titulo de info do progresso global
        self.label_progress_total = Gtk.Label(halign=Gtk.Align.START)
        grid.attach(self.label_progress_total, 0, 2, 6, 1)

        # Progresso da conversão do arquivo
        self.progressbar_atual = Gtk.ProgressBar(show_text=True)
        grid.attach(self.progressbar_atual, 0, 3, 6, 1)

        # Titulo do arquivo
        self.label_atual = Gtk.Label(halign=Gtk.Align.START)
        grid.attach(self.label_atual, 0, 4, 6, 1)

        self.get_content_area().pack_start(grid, True, True, 0)
        self.show_all()

        # Inicia a threa de conversão de vídeos
        thread = Thread(target=self.processa_videos)
        thread.daemon = True
        thread.start()

    def update_progess(self, titulo_barra_total, progresso_total, titulo_label_total, titulo_label_atual):
        """        
        Atualiza os contadores do arquivo atual e progresso total
        """
        
        self.progress_bar_total.set_text(titulo_barra_total)
        self.progress_bar_total.set_fraction(progresso_total)  # O processo deve ser entre 0.0 e 1.0
        self.label_progress_total.set_text(titulo_label_total)
        self.label_atual.set_text(titulo_label_atual)

        return False

    def update_progess_arquivo(self, progresso_conversao):
        """
        Atualiza o progress bar da conversão do arquivo
        """
        
        self.progressbar_atual.set_fraction(progresso_conversao)  # O processo deve ser entre 0.0 e 1.0
        return False

    def processa_videos(self):
        """
        Efetua a conversão dos videos
        """
        
        DURATION = "Duration:"
        FRAME = "frame="
        TIME = "time="

        # Recupera o codec e o path do ffmpeg
        codec_idx = get_app_settings("codec_video")
        codec_idx = codec_idx if codec_idx is not None else "0"
        codec_info = get_codec_info(CODECS_VIDEO[int(codec_idx)])

        for arquivo in self.lista_arquivos:
            try:

                if not os.path.isfile(arquivo):
                    debug("Ignorando aquivo inexistente: " + arquivo)
                    self.failed = True
                    continue

                self.completed_size = self.completed_size + os.stat(arquivo).st_size
                novo_arquivo = self.dir_destino + os.sep + get_destino_arquivo(arquivo)
                arquivo_copia = self.dir_destino + os.sep + os.path.basename(arquivo)

                # Monta os parâmetros para a criação do novo video, de acordo com o codec escolhido
                args = [get_caminho_ffmpeg(), "-hide_banner", "-i", arquivo_copia]
                args.extend(codec_info["params"])
                novo_arquivo = novo_arquivo[:novo_arquivo.rindex('.')] + codec_info["sufixo"]
                args.append(novo_arquivo)

                # Estatísticas da conversão total
                titulo_barra_total = "[" + to_human_size(self.completed_size) + "/" + to_human_size(self.total) + "]"
                titulo_label_total = "Original: " + os.path.basename(arquivo) + " (" + to_human_size(os.stat(arquivo).st_size) + ")"

                if os.path.isfile(novo_arquivo):
                    titulo_label_atual = "Compactado: " + os.path.basename(novo_arquivo)
                else:
                    titulo_label_atual = "Compactado: <Falha ao ler os dados do arquivo>"

                progresso_total = self.completed_size / self.total  # Percentual do progresso

                # Atualiza as estatíticas do total e o nome do arquivo de destino
                GLib.idle_add(self.update_progess, titulo_barra_total, progresso_total, titulo_label_total, titulo_label_atual)

                # Cria o diretório, se não existir
                directory = os.path.dirname(novo_arquivo)
                if not os.path.exists(directory):
                    debug("Criando o diretório " + directory)
                    os.makedirs(directory)

                # Verifica se o vídeo de destino existe
                if os.path.isfile(novo_arquivo):
                    debug("Removendo arquivo de destino existente: " + novo_arquivo)
                    os.remove(novo_arquivo)

                max_secs = 0
                cur_secs = 0

                # Checa se o usuário interrrompeu a conversão
                if self.must_stop:
                    return None

                # Efetua a conversão do arquivo de video
                debug("Executando aplicação: " + str(args))

                global g_processo_ffmpeg
                g_processo_ffmpeg = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

                # Inicia o processo e itera entre as linhas recebidas no stdout
                for line in iter(g_processo_ffmpeg.stdout.readline, ''):
                    if DURATION in line:
                        # Essa linha contém o tamanho total do vídeo
                        try:
                            tmp = line[line.find(DURATION):]
                            tmp = tmp[tmp.find(" ") + 1:]
                            tmp = tmp[0: tmp.find(".")]
                            x = time.strptime(tmp, '%H:%M:%S')
                            max_secs = datetime.timedelta(hours=x.tm_hour, minutes=x.tm_min, seconds=x.tm_sec).total_seconds()
                        except ValueError:
                            debug("Falha ao converter o horário: " + tmp)

                    elif line.startswith(FRAME) and TIME in line:
                        try:
                            # Captura o tempo da conversão (timestamp)
                            tmp = line[line.find(TIME):]
                            tmp = tmp[tmp.find("=") + 1: tmp.find(".")]
                            x = time.strptime(tmp, '%H:%M:%S')
                            cur_secs = datetime.timedelta(hours=x.tm_hour, minutes=x.tm_min, seconds=x.tm_sec).total_seconds()
                        except ValueError:
                            debug("Falha ao converter o horário: " + tmp)

                    # Atualiza o progresso da conversão do arquivo de destino
                    if cur_secs > 0 and max_secs > 0:
                        GLib.idle_add(self.update_progess_arquivo, cur_secs / max_secs)

                # Finaliza o processo do ffmpeg
                g_processo_ffmpeg.stdout.close()
                g_processo_ffmpeg.wait()

                if os.path.isfile(arquivo):
                    debug("Vídeo original: " + arquivo + " (" + to_human_size(os.stat(arquivo).st_size) + ")")

                if os.path.isfile(novo_arquivo):
                    debug("Vídeo convertido: " + novo_arquivo + " (" + to_human_size(os.stat(novo_arquivo).st_size) + ")")

                # Remove a cópia do video original
                if 'True' == get_app_settings("remover_video_apos_conversao"):
                    video_original = os.path.dirname(novo_arquivo) + os.sep + os.path.basename(arquivo)
                    if os.path.isfile(video_original):
                        debug("Removendo a cópia do video original: " + video_original)
                        os.remove(video_original)

            except Exception as e:
                debug("Falha ao converter o arquivo de vídeo " + arquivo + " : ", str(e))
                self.failed = True

        self.close()


class FileCopyProgressDialog(Gtk.Dialog):
    """
    Dialog utilizada para exibir o progresso da cópia de arquivos
    """
    
    must_stop = False
    failed = False
    total = 0
    completed_size = 0

    def __init__(self, parent, arquivos, destino):
        Gtk.Dialog.__init__(self, "Copiando arquivos ", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL))

        self.set_size_request(250, 150)
        self.set_border_width(10)
        self.lista_arquivos = arquivos
        self.dir_destino = destino

        # Container principal
        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(4)
        grid.set_row_spacing(6)

        for arquivo in self.lista_arquivos:
            self.total = self.total + os.stat(arquivo).st_size

        # Label com o título da atividade
        grid.attach(Gtk.Label(label="Efetuando a cópia de " + str(len(arquivos)) + 
                              " arquivos (" + to_human_size(self.total) + ")", halign=Gtk.Align.START), 0, 0, 6, 1)

        # Barra de progresso global
        self.progress_bar = Gtk.ProgressBar(show_text=True)
        grid.attach(self.progress_bar, 0, 1, 6, 1)

        # Label do progresso do arquivo
        self.label_progress = Gtk.Label(halign=Gtk.Align.START)
        grid.attach(self.label_progress, 0, 2, 6, 1)

        self.get_content_area().pack_start(grid, True, True, 0)
        self.show_all()

        thread = Thread(target=self.copia_arquivos)
        thread.daemon = True
        thread.start()

    def update_progess(self, titulo_progresso, progresso_copia, titulo_copia):
        """
        Atualiza o progress bar da cópia dos arquivos 
        """
        self.progress_bar.set_fraction(progresso_copia)  # O processo deve ser entre 0.0 e 1.0
        self.progress_bar.set_text(titulo_progresso)
        self.label_progress.set_text(titulo_copia)
        return False

    def copia_arquivos(self):
        """
        Efetua a cópia dos arquivos
        """
        total_arquivos = len(self.lista_arquivos)
        for i, arquivo in enumerate(self.lista_arquivos):
            try:
                self.completed_size = self.completed_size + os.stat(arquivo).st_size

                titulo_progresso = "[" + to_human_size(self.completed_size) + "/" + to_human_size(self.total) + "]"
                progresso_copia = self.completed_size / self.total  # Percentual do progresso
                titulo_copia = "[" + str(i) + "/" + str(total_arquivos) + "] " + os.path.basename(arquivo) + " (" + to_human_size(os.stat(arquivo).st_size) + ")"

                GLib.idle_add(self.update_progess, titulo_progresso, progresso_copia, titulo_copia)

                # Verifica se a cópia foi interrompida
                if self.must_stop:
                    return None

                # Cria o diretório, se não existir
                novo_arquivo = self.dir_destino + os.sep + get_destino_arquivo(arquivo)
                dir_novo_arquivo = os.path.dirname(novo_arquivo)
                if not os.path.exists(dir_novo_arquivo):
                    try:
                        debug("Criando o diretório " + dir_novo_arquivo)
                        os.makedirs(dir_novo_arquivo)
                    except Exception as e:
                        debug("Falha ao criar o diretório de destino [" + dir_novo_arquivo + "]: " + str(e))
                        continue

                # Sempre copia o arquivo
                debug("Copiando " + arquivo + " -> " + novo_arquivo)
                shutil.copy2(arquivo, novo_arquivo)

                # Se selecionado a opção, remover após a cópia
                if 'True' == get_app_settings("remover_apos_copia"):
                    try:
                        debug("Removendo arquivo de origem " + arquivo)
                        os.remove(arquivo)
                    except Exception as e:
                        debug("Falha ao remover o arquivo de origem após a cópia [" + arquivo + "]: " + str(e))
            except Exception as e:
                debug("Falha durante a cópia do arquivo [" + arquivo + "]: " + str(e))
                continue

        self.close()


class InputDialog(Gtk.Dialog):
    """
    Dialog de solicitação de dados em um campo de texto ou combo
    """
    
    text_field = None
    combo_box = None

    def __init__(self, parent, message, default, opcoes):
        Gtk.Dialog.__init__(self, "Solicitação de informação do usuário", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(350, 150)
        self.set_border_width(10)

        topbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        topbox.pack_start(Gtk.Label(label=message, halign=Gtk.Align.START), True, True, 0)

        debug("Solicitação de informação ao usuário: " + message)
        if opcoes is None:
            # Campo de texto
            self.text_field = Gtk.Entry()
            self.text_field.set_text(default)
            topbox.pack_start(self.text_field, True, True, 0)
        else:
            self.combo_box = Gtk.ComboBoxText()
            # Campo de texto
            for i, word in enumerate(opcoes.split('|')):
                self.combo_box.append_text(word)
                if default and unicode(word) == unicode(default):
                    self.combo_box.set_active(i)

            topbox.pack_start(self.combo_box, True, True, 0)

        self.get_content_area().pack_start(topbox, False, False, 0)
        self.show_all()

    def do_valida_campos(self):
        if self.text_field is not None and not self.text_field.get_text().strip():
            return show_message('Campo obrigatório não informado:', 'É necessário especificar o valor do campo.')

        if self.combo_box is not None and not self.combo_box.get_active_text():
            return show_message('Campo obrigatório não informado:', 'É necessário selecionar um item.')

        return Gtk.ResponseType.OK

    def show_and_get_info(self):
        while self.run() == Gtk.ResponseType.OK:
            if self.do_valida_campos() is not None:
                if self.text_field is not None:
                    resp = self.text_field.get_text().strip()
                else:
                    resp = self.combo_box.get_active_text()
                self.destroy()
                return resp

        self.destroy()
        return None


class ConfigDialog(Gtk.Dialog):
    """
    Dialog de configuração da aplicação
    """
    
    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Configurações da aplicação", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(400, 300)
        self.set_border_width(10)

        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(2)
        grid.set_row_spacing(2)

        grid_check = Gtk.Grid()

        # Apenas fotos e videos
        self.check_fotos_videos = Gtk.CheckButton("Copiar apenas as fotos e os vídeos")
        self.check_fotos_videos.set_active('True' == get_app_settings("apenas_fotos_e_videos"))
        grid_check.attach(self.check_fotos_videos, 0, 0, 3, 1)

        # Sobrescrever
        self.check_sobrescrever = Gtk.CheckButton("Sobrescrever os arquivos de destino")
        self.check_sobrescrever.set_active('True' == get_app_settings("sobrescrever_arquivos"))
        grid_check.attach(self.check_sobrescrever, 4, 0, 3, 1)

        # Remover após copia
        self.check_remover_copia = Gtk.CheckButton("Remover os arquivos originais após a cópia")
        self.check_remover_copia.set_active('True' == get_app_settings("remover_apos_copia"))
        grid_check.attach(self.check_remover_copia, 0, 1, 3, 1)

        # Exibir resolução dos arquivos
        self.check_exibir_resolucao = Gtk.CheckButton("Exibir a resolução dos arquivos")
        self.check_exibir_resolucao.set_active('True' == get_app_settings("exibir_resolucao_arquivos"))
        grid_check.attach(self.check_exibir_resolucao, 4, 1, 3, 1)
        
        # Comprimir videos
        self.check_recode = Gtk.CheckButton("Re-codificar arquivos de vídeo")
        self.check_recode.set_active('True' == get_app_settings("recodificar_videos"))
        grid_check.attach(self.check_recode, 0, 2, 3, 1)

        # Formato do video
        flowbox = Gtk.FlowBox()

        flowbox.add(Gtk.Label(label="Formato do vídeo:", halign=Gtk.Align.START))
        self.combo_codecs = Gtk.ComboBoxText()
        
        for codec in CODECS_VIDEO:
            self.combo_codecs.append_text(codec)
            
        self.combo_codecs.set_active(0)
        self.combo_codecs.set_entry_text_column(1)
        codec_idx = get_app_settings("codec_video")
        if codec_idx is not None:
            self.combo_codecs.set_active(int(codec_idx))
            
        flowbox.add(self.combo_codecs)

        grid_check.attach(flowbox, 4, 2, 3, 1)

        # Remover Videos convertidos
        self.check_remover_video = Gtk.CheckButton("Remover a cópia do video original após a conversão")
        self.check_remover_video.set_active('True' == get_app_settings("remover_video_apos_conversao"))
        grid_check.attach(self.check_remover_video, 0, 3, 3, 1)

        grid.attach(grid_check, 0, 0, 6, 3)

        # Campo Destino

        self.edit_caminho_ffmpeg = Gtk.Entry()
        self.edit_caminho_ffmpeg.set_text(get_app_settings("caminho_ffmpeg"))

        button = Gtk.Button.new_from_icon_name("document-open", Gtk.IconSize.BUTTON)
        button.connect("clicked", self.do_click_seleciona_ffmpeg)

        box_destino = Gtk.Box()
        box_destino.pack_start(Gtk.Label(label="Caminho do ffmpeg:", halign=Gtk.Align.START), False, False, 0)
        box_destino.pack_start(self.edit_caminho_ffmpeg, True, True, 4)
        box_destino.pack_end(button, False, False, 0)

        grid.attach(box_destino, 0, 3, 6, 1)

        # Lista de videos
        self.taskstore_videos = Gtk.ListStore(str)
        self.treeview_videos = Gtk.TreeView(model=self.taskstore_videos)
        self.treeview_videos.append_column(Gtk.TreeViewColumn("Extensão dos arquivos de Video", Gtk.CellRendererText(), text=0))

        scrollable_treelist_videos = Gtk.ScrolledWindow()
        scrollable_treelist_videos.set_vexpand(True)
        scrollable_treelist_videos.set_hexpand(True)
        scrollable_treelist_videos.add(self.treeview_videos)

        grid_video = Gtk.Grid()
        grid_video.attach(scrollable_treelist_videos, 0, 0, 6, 6)

        for video in get_app_settings("extensoes_video").split('|'):
            self.taskstore_videos.append([video])

        flowbox = Gtk.FlowBox()
        button = Gtk.Button.new_from_icon_name("list-add", Gtk.IconSize.MENU)
        button.connect("clicked", self.do_click_add_video)
        flowbox.add(button)
        grid_video.attach(flowbox, 7, 3, 1, 1)

        flowbox = Gtk.FlowBox()
        button = Gtk.Button.new_from_icon_name("list-remove", Gtk.IconSize.MENU)
        button.connect("clicked", self.do_click_del_video)
        flowbox.add(button)
        grid_video.attach(flowbox, 7, 4, 1, 1)

        grid.attach(grid_video, 0, 4, 3, 6)

        # Lista de Fotos
        self.taskstore_fotos = Gtk.ListStore(str)
        self.treeview_fotos = Gtk.TreeView(model=self.taskstore_fotos)
        self.treeview_fotos.append_column(Gtk.TreeViewColumn("Extensão dos arquivos de Foto", Gtk.CellRendererText(), text=0))

        scrollable_treelist_fotos = Gtk.ScrolledWindow()
        scrollable_treelist_fotos.set_vexpand(True)
        scrollable_treelist_fotos.set_hexpand(True)
        scrollable_treelist_fotos.add(self.treeview_fotos)

        grid_foto = Gtk.Grid()
        grid_foto.attach(scrollable_treelist_fotos, 0, 0, 6, 6)

        for foto in get_app_settings("extensoes_foto").split('|'):
            self.taskstore_fotos.append([foto])

        flowbox = Gtk.FlowBox()
        button = Gtk.Button.new_from_icon_name("list-add", Gtk.IconSize.MENU)
        button.connect("clicked", self.do_click_add_foto)
        flowbox.add(button)

        grid_foto.attach(flowbox, 7, 3, 1, 1)

        flowbox = Gtk.FlowBox()
        button = Gtk.Button.new_from_icon_name("list-remove", Gtk.IconSize.MENU)
        button.connect("clicked", self.do_click_del_foto)
        flowbox.add(button)
        grid_foto.attach(flowbox, 7, 4, 1, 1)

        grid.attach(grid_foto, 4, 4, 3, 6)

        self.get_content_area().pack_start(grid, False, False, 0)
        self.show_all()

    def do_click_seleciona_ffmpeg(self, widget):  # @UnusedVariable
        debug("Selecionando o caminho do FFMPEG")

        dialog = Gtk.FileChooserDialog("Selecione o caminho do ffmpeg ", self, Gtk.FileChooserAction.OPEN,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        caminho = self.edit_caminho_ffmpeg.get_text().strip()
        if os.path.isfile(caminho):
            dialog.set_current_folder(caminho)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.edit_caminho_ffmpeg.set_text(dialog.get_filename())
            debug("Caminho do ffmpeg selecionado: " + dialog.get_filename())

        dialog.destroy()

    def do_click_del_video(self, widget):  # @UnusedVariable
        self.remove_item("video")

    def do_click_add_video(self, widget):  # @UnusedVariable
        self.add_item("video")

    def do_click_del_foto(self, widget):  # @UnusedVariable
        self.remove_item("foto")

    def do_click_add_foto(self, widget):  # @UnusedVariable
        self.add_item("foto")

    def add_item(self, titulo):
        info = InputDialog(main_window, 'Informe a extensão do arquivo de ' + titulo, '', None).show_and_get_info()
        if info is not None:
            store = self.taskstore_videos if titulo == "video" else self.taskstore_fotos
            store.append([info])

    def remove_item(self, titulo):
        debug("Removendo item da lista de " + titulo)
        tree = self.treeview_fotos
        store = self.taskstore_fotos
        if titulo == "video":
            store = self.taskstore_videos
            tree = self.treeview_videos

        select = tree.get_selection()
        treeiter = select.get_selected()

        if treeiter[1] is None:
            return show_message("Não é possível excluir", "É necessário selecionar um dos ítens para continuar.")

        store.remove(treeiter)

    def show_and_get_info(self):
        while self.run() == Gtk.ResponseType.OK:
            set_app_settings("remover_apos_copia", str(self.check_remover_copia.get_active()))
            set_app_settings("sobrescrever_arquivos", str(self.check_sobrescrever.get_active()))
            set_app_settings("recodificar_videos", str(self.check_recode.get_active()))
            set_app_settings("caminho_ffmpeg", self.edit_caminho_ffmpeg.get_text().strip())
            set_app_settings("codec_video", str(self.combo_codecs.get_active()))
            set_app_settings("apenas_fotos_e_videos", str(self.check_fotos_videos.get_active()))
            set_app_settings("exibir_resolucao_arquivos", str(self.check_exibir_resolucao.get_active()))                 

            videos = ""
            for row in self.taskstore_videos:
                videos = videos + "|" + row[0]
            videos = videos[1:]
            set_app_settings("extensoes_video", videos)

            fotos = ""
            for row in self.taskstore_fotos:
                fotos = fotos + "|" + row[0]
            fotos = fotos[1:]
            set_app_settings("extensoes_foto", fotos)

        self.destroy()
        return None


class LogViewerDialog(Gtk.Dialog):
    """
    Dialogo para exibição do log
    """
        
    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Log da aplicação", parent, 0, (Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(1024, 600)
        self.set_border_width(10)

        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_hexpand(True)
        scrolledwindow.set_vexpand(True)

        self.grid = Gtk.Grid()
        self.grid.attach(scrolledwindow, 0, 1, 3, 1)

        self.textview = Gtk.TextView()
        scrolledwindow.add(self.textview)

        # Carrega o arquivo de log
        self.textview.get_buffer().set_text(open(ARQUIVO_LOG).read())

        self.get_content_area().pack_start(self.grid, True, True, 0)
        self.show_all()

    def show_and_get_info(self):
        self.run()
        self.destroy()
        return None


class MapeamentoDialog(Gtk.Dialog):
    """
    Dialogo para mapeamento dos diretórios de destino
    """

    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Mapeamento dos diretórios de destino", parent, 0, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(500, 400)
        self.set_border_width(10)

        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_hexpand(True)
        scrolledwindow.set_vexpand(True)

        self.grid = Gtk.Grid()
        self.grid.attach(scrolledwindow, 0, 1, 3, 1)

        self.textview = Gtk.TextView()
        scrolledwindow.add(self.textview)

        # Carrega o mapeamento atual
        global g_dic_mapeamento_dir_destino
        lines = ""
        
        for key in sorted(g_dic_mapeamento_dir_destino.iterkeys()):
            if key in g_dic_mapeamento_dir_origem:            
                lines = lines + key + " => " + g_dic_mapeamento_dir_destino[key] + "   #" + g_dic_mapeamento_dir_origem[key] + "\n"
            else:
                lines = lines + key + " => " + g_dic_mapeamento_dir_destino[key] + "\n"

        self.textview.get_buffer().set_text(lines)

        self.get_content_area().pack_start(self.grid, True, True, 0)
        self.show_all()

    def show_and_update_file_list(self):
        global g_dic_mapeamento_dir_destino
        while self.run() == Gtk.ResponseType.OK:
            buf = self.textview.get_buffer()
            resp = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
            for line in resp.splitlines():
                key = line[:line.find("=>")].strip()
                value = line[line.find("=>") + 2:line.find("#")].strip() if '#' in line else line[line.find("=>") + 2:].strip()
                g_dic_mapeamento_dir_destino[key] = value

            self.destroy()
            return True

        self.destroy()
        return False


class MainWindow(Gtk.Window):
    """
    Janela principal da aplicação
    """
    
    COLUNAS_GRID = ["Copiar", "Status", "Arquivo", "Destino", "Tipo", "Tamanho", "Detalhes"]
    popupMenuTree = Gtk.Menu()

    def __init__(self):
        Gtk.Window.__init__(self, title="Photo Sync - " + VERSAO_APPLICACAO)

        self.set_icon_name("application-x-executable")
        Gtk.Settings().set_property('gtk_button_images', True)

        # Clipboard para cópia do texto
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        self.set_resizable(True)
        self.set_border_width(10)
        self.set_default_size(640, 480)
        self.set_size_request(640, 480)

        # Container principal
        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(4)
        grid.set_row_spacing(6)

        # Campo Origem
        grid.attach(Gtk.Label(label="Diretório de Origem:", halign=Gtk.Align.START), 0, 0, 1, 1)
        self.edit_origem = Gtk.Entry()
        self.edit_origem.set_activates_default(True)
        self.edit_origem.set_text(get_app_settings("dir_origem"))

        grid.attach(self.edit_origem, 1, 0, 6, 1)

        button = Gtk.Button.new_from_icon_name("folder-open", Gtk.IconSize.BUTTON)
        button.connect("clicked", self.do_click_origem)
        flowbox = Gtk.FlowBox()
        flowbox.add(button)
        grid.attach(flowbox, 7, 0, 1, 1)
        self.labelStatusFrom = Gtk.Label(label="", halign=Gtk.Align.START)
        grid.attach(self.labelStatusFrom, 0, 1, 8, 1)

        # Campo Destino
        grid.attach(Gtk.Label(label="Diretório de Destino:", halign=Gtk.Align.START), 0, 2, 1, 1)
        self.edit_destino = Gtk.Entry()
        self.edit_destino.set_text(get_app_settings("dir_destino"))
        grid.attach(self.edit_destino, 1, 2, 6, 1)
        button = Gtk.Button.new_from_icon_name("folder-open", Gtk.IconSize.BUTTON)
        button.connect("clicked", self.do_click_destino)
        flowbox = Gtk.FlowBox()
        flowbox.add(button)

        grid.attach(flowbox, 7, 2, 1, 1)
        self.labelStatusTo = Gtk.Label(label="", halign=Gtk.Align.START)
        grid.attach(self.labelStatusTo, 0, 3, 8, 1)

        # Barra de botões

        # Ler aquivos
        self.button_ler_arquivos = create_icon_and_label_button("Atualizar", "view-refresh")
        self.button_ler_arquivos.connect("clicked", self.do_click_check_files)
        grid.attach(self.button_ler_arquivos, 0, 4, 1, 1)

        # Sincronizar
        self.button_sync_arquivos = create_icon_and_label_button("Sincronizar", "system-run")
        self.button_sync_arquivos.set_sensitive(False)
        self.button_sync_arquivos.connect("clicked", self.do_click_sync_files)
        grid.attach(self.button_sync_arquivos, 1, 4, 1, 1)

        # Mapeamento
        self.button_mapeamento = create_icon_and_label_button("Mapeamento", "document-properties")
        self.button_mapeamento.set_sensitive(False)
        self.button_mapeamento.connect("clicked", self.do_click_mapeamento_dir)
        grid.attach(self.button_mapeamento, 2, 4, 1, 1)

        # Configurações
        self.button_config = create_icon_and_label_button("Configurações", "applications-system")
        self.button_config.connect("clicked", self.do_click_config)
        grid.attach(self.button_config, 3, 4, 1, 1)

        # Logs
        button = create_icon_and_label_button("Logs", "system-search")
        button.connect("clicked", self.do_click_logs)
        grid.attach(button, 4, 4, 1, 1)

        # Sair
        button = create_icon_and_label_button("Fechar", "window-close")
        button.connect("clicked", self.do_click_close)
        grid.attach(button, 7, 4, 1, 1)

        # grid de arquivos

        # Cria o grid
        self.store = Gtk.ListStore(bool, str, str, str, str, str, str)

        self.filtro = self.store.filter_new()
        # self.filtro.set_visible_func(self.do_filter_grid)
        cellRenderer = Gtk.CellRendererText()

        # Adiciona as COLUNAS_GRID ao TreeView
        self.treeview = Gtk.TreeView(model=self.store)
        self.treeview.connect("button_press_event", self.do_show_popup)

        # Colunas 0 e 1 não são texto
        col1 = Gtk.TreeViewColumn("Copiar", Gtk.CellRendererToggle(), active=0)
        col1.set_sort_column_id(0)
        self.treeview.append_column(col1)

        col2 = Gtk.TreeViewColumn("Status", Gtk.CellRendererPixbuf(), icon_name=1)
        col2.set_sort_column_id(1)
        self.treeview.append_column(col2)

        # Adiciona as demais COLUNAS_GRID
        for i, column_title in enumerate(self.COLUNAS_GRID):
            column = Gtk.TreeViewColumn(column_title, cellRenderer, text=i)
            if i > 1:  # Colunas 0 e 1 são do checkbox e icon e foram adicionadas anteriormente
                self.treeview.append_column(column)
            self.store.set_sort_func(i, compareTreeItem, None)
            column.set_sort_column_id(i)

        self.treeview.connect("row-activated", self.on_tree_double_clicked)

        # Adiciona o treeview a um scrollwindow
        scrollable_treelist = Gtk.ScrolledWindow()
        scrollable_treelist.set_vexpand(True)
        scrollable_treelist.add(self.treeview)
        grid.attach(scrollable_treelist, 0, 5, 8, 8)

        # Label de seleção dos arquivos
        self.label_status_copia = Gtk.Label(label="", halign=Gtk.Align.START)
        grid.attach(self.label_status_copia, 0, 13, 8, 1)

        self.add(grid)

        i0 = Gtk.MenuItem("Desmarcar todos os arquivos")
        i0.connect("activate", self.do_desmarcar_todos)
        self.popupMenuTree.append(i0)
        i1 = Gtk.MenuItem("Marcar todos os videos")
        i1.connect("activate", self.do_marca_todos_videos)
        self.popupMenuTree.append(i1)
        i2 = Gtk.MenuItem("Marcar todas as fotos")
        i2.connect("activate", self.do_marca_todas_fotos)
        self.popupMenuTree.append(i2)
        i3 = Gtk.MenuItem("Marcar videos não H265")
        i3.connect("activate", self.do_marcar_nao_h265)
        self.popupMenuTree.append(i3)
        i4 = Gtk.MenuItem("Apagar arquivos marcados")
        i4.connect("activate", self.do_apagar_selecionados)
        self.popupMenuTree.append(i4)

        self.popupMenuTree.show_all()

    def do_show_popup(self, tv, event):  # @UnusedVariable
        if event.button == 3:
            self.popupMenuTree.popup(None, None, None, None, 0, Gtk.get_current_event_time())

    def do_apagar_selecionados(self, widget):  # @UnusedVariable
        debug("MenuItem: Apagar arquivos marcados")
        arquivos = self.do_monta_lista_arquivos_copiar()
        if len(arquivos) > 0:
            dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.QUESTION, Gtk.ButtonsType.YES_NO, "Confirmação da exclusão")
            dialog.format_secondary_text("Você realmente deseja remover os " + str(len(arquivos)) + " arquivos marcados?")
            response = dialog.run()
            if response == Gtk.ResponseType.YES:
                for arquivo in arquivos:
                    debug("Removendo arquivo " + arquivo)
                    os.remove(arquivo)
                self.do_monta_lista_arquivos()
            dialog.destroy()

    def do_marcar_nao_h265(self, widget):  # @UnusedVariable
        debug("MenuItem: Marcar videos não H265")
        for row in self.store:
            if self.is_video(row[2]) and 'hevc' not in row[6]:
                row[0] = True

        self.do_atualiza_contador_selecao()

    def do_marca_todas_fotos(self, widget):  # @UnusedVariable
        debug("MenuItem: Marcar todas as fotos")
        for row in self.store:
            if self.is_foto(row[2]):
                row[0] = True

    def do_marca_todos_videos(self, widget):  # @UnusedVariable
        debug("MenuItem: Marcar todos os videos")
        for row in self.store:
            if self.is_video(row[2]):
                row[0] = True

        self.do_atualiza_contador_selecao()

    def do_desmarcar_todos(self, widget):  # @UnusedVariable
        debug("MenuItem: Desmarcar todos os arquivos")
        for row in self.store:
            row[0] = False

        self.do_atualiza_contador_selecao()

    def do_click_origem(self, widget):  # @UnusedVariable
        self.do_seleciona_dir("origem")

    def do_click_destino(self, widget):  # @UnusedVariable
        self.do_seleciona_dir("destino")

    def do_seleciona_dir(self, titulo):
        debug("Selecionando diretório de " + titulo)

        editor = self.edit_origem if titulo == "origem" else self.edit_destino

        dialog = Gtk.FileChooserDialog("Selecione o diretório de " + titulo, self, Gtk.FileChooserAction.SELECT_FOLDER,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        current_dir = editor.get_text().strip()
        if os.path.isdir(current_dir):
            dialog.set_current_folder(current_dir)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            editor.set_text(dialog.get_filename())
            debug("Diretório de " + titulo + " selecionado: " + dialog.get_filename())
            set_app_settings("dir_" + titulo, dialog.get_filename())

        dialog.destroy()

    def get_tipo_arquivo(self, arquivo):
        tipo = "Desconhecido"
        if self.is_foto(arquivo):
            tipo = "Foto"
        elif self.is_video(arquivo):
            tipo = "Video"
        return tipo

    def get_file_is_sync(self, arquivo):
        global g_lista_arquivos_destino
        arquivos = g_lista_arquivos_destino.get(os.path.basename(arquivo), [])
        tamanho_origem = os.stat(arquivo).st_size
        found = False
        if len(arquivos) > 0:
            for  dests in arquivos:
                found = found or tamanho_origem == os.stat(dests).st_size
        return found

    def get_icone_arquivo(self, sync):
        mover = 'True' == get_app_settings("remover_apos_copia")
        resp = "forward" if mover else "go-down"

        if sync:
            sobrescreve = 'True' == get_app_settings("sobrescrever_arquivos")
            resp = "gtk-stop" if sobrescreve else "ok"

        return resp

    def do_monta_lista_arquivos(self):
        active = g_leitura_origem_finalizada and g_leitura_destino_finalizada

        if active:
            debug("Populando a grid de arquivos")

            global g_lista_arquivos_origem
            global g_dic_info_arquivos_origem

            # Verifica se deve sobrescrever os arqivos existentes
            sobrescrever = 'True' == get_app_settings("sobrescrever_arquivos")

            self.store.clear()
            src = self.edit_origem.get_text().strip()

            pos_src = len(src) if src.endswith(os.sep) else len(src) + 1
            
            for arquivo in g_lista_arquivos_origem:
                sync = self.get_file_is_sync(arquivo)
                icon = self.get_icone_arquivo(sync)
                tamanho = to_human_size(os.stat(arquivo).st_size)
                detalhes = g_dic_info_arquivos_origem[arquivo]
                arquivo_abr = arquivo[pos_src:]
                tipo_arquivo = self.get_tipo_arquivo(arquivo)
                destino = get_destino_arquivo(arquivo)

                # Se for para sobrescrever, sync deve ser sempre falso
                if sobrescrever:
                    sync = False

                self.store.append([
                    not sync,
                    icon,
                    arquivo_abr,
                    destino,
                    tipo_arquivo,
                    tamanho,
                    detalhes
                ])

            # Habilita os botões
            self.button_ler_arquivos.set_sensitive(active)
            self.button_sync_arquivos.set_sensitive(active)
            self.button_mapeamento.set_sensitive(active)

            # Atualiza o contador
            self.do_atualiza_contador_selecao()
            debug("Grid de arquivos populada")

    def do_read_file_list_origem(self):
        global g_lista_arquivos_origem
        global g_leitura_origem_finalizada
        global g_dic_info_arquivos_origem
        g_dic_info_arquivos_origem = {}

        # Monta a lista de arquivos
        g_lista_arquivos_origem = [y for x in os.walk(self.edit_origem.get_text()) for y in glob(os.path.join(x[0], '*.*'))]
        tamanho = 0
        for arquivo in g_lista_arquivos_origem:
            try:
                # Carrega a informação do arquivo
                g_dic_info_arquivos_origem[arquivo] = self.get_file_info(arquivo)

                tamanho = tamanho + os.stat(arquivo).st_size  # in bytes
            except:
                debug("Falha ao ler o arquivo de origem " + arquivo)

        self.labelStatusFrom.set_text("Arquivos no diretório de origem: " + str(len(g_lista_arquivos_origem)) + " (" + to_human_size(tamanho) + ")")
        debug(self.labelStatusFrom.get_text())
        g_leitura_origem_finalizada = True
        self.do_monta_lista_arquivos()
        debug("Consulta da lista de arquivos de origem concluída")

    def do_read_file_list_destino(self):
        global g_leitura_destino_finalizada
        global g_lista_arquivos_destino
        g_lista_arquivos_destino = {}
        lista_arquivos_destino = [y for x in os.walk(self.edit_destino.get_text()) for y in glob(os.path.join(x[0], '*.*'))]
        tamanho = 0
        for arquivo in lista_arquivos_destino:
            try:
                tamanho = tamanho + os.stat(arquivo).st_size  # in bytes
                nome = os.path.basename(arquivo)
                arquivos = g_lista_arquivos_destino.get(nome, [])
                arquivos.append(arquivo)
                g_lista_arquivos_destino[nome] = arquivos
            except:
                debug("Falha ao ler o arquivo de destino " + arquivo)

        self.labelStatusTo.set_text("Arquivos no diretório de destino: " + str(len(lista_arquivos_destino)) + " (" + to_human_size(tamanho) + ")")
        debug(self.labelStatusTo.get_text())
        g_leitura_destino_finalizada = True
        self.do_monta_lista_arquivos()
        debug("Consulta da lista de arquivos de destino concluída")

    def do_click_check_files(self, widget):  # @UnusedVariable
        debug("Validando os diretórios")

        if not os.path.isdir(self.edit_origem.get_text()):
            return show_message("Diretório inexistente", "Não foi possível encontrar o diretório de origem.")

        if not os.path.isdir(self.edit_destino.get_text()):
            return show_message("Diretório inexistente", "Não foi possível encontrar o diretório de destino.")

        debug("Verificando a lista de arquivos")

        global g_lista_arquivos_origem
        global g_lista_arquivos_destino
        global g_leitura_origem_finalizada
        global g_leitura_destino_finalizada
        global g_dic_mapeamento_dir_origem
        global g_dic_mapeamento_dir_destino

        g_lista_arquivos_origem = []
        g_lista_arquivos_destino = {}
        g_leitura_origem_finalizada = False
        g_leitura_destino_finalizada = False
        g_dic_mapeamento_dir_origem = {}
        g_dic_mapeamento_dir_destino = {}

        # Desabilita os botões
        self.button_ler_arquivos.set_sensitive(False)
        self.button_sync_arquivos.set_sensitive(False)
        self.button_mapeamento.set_sensitive(False)

        self.store.clear()

#         Thread(target=self.do_read_file_list_origem).start()
#         Thread(target=self.do_read_file_list_destino).start()

        # Compara a lista de arquivos da origem com o destino
        self.do_read_file_list_origem()
        self.do_read_file_list_destino()

    def do_atualiza_contador_selecao(self):
        cont = 0
        cont_video = 0
        cont_foto = 0
        cont_outro = 0
        size = 0
        size_video = 0
        size_foto = 0
        size_outro = 0

        for row in self.store:
            if row[0]:
                arquivo = self.edit_origem.get_text() + os.sep + row[2]
                cont += 1
                size += os.stat(arquivo).st_size

                if self.is_video(arquivo):
                    cont_video += 1
                    size_video += os.stat(arquivo).st_size
                elif self.is_foto(arquivo):
                    cont_foto += 1
                    size_foto += os.stat(arquivo).st_size
                else:
                    cont_outro += 1
                    size_outro += os.stat(arquivo).st_size

        self.label_status_copia.set_text("Arquivos selecionados: " + str(cont) + " / " + str(len(self.store)) + " (" + to_human_size(size) + ") - Videos: " + 
                                         str(cont_video) + " (" + to_human_size(size_video) + ") - Fotos: " + str(cont_foto) + " (" + to_human_size(size_foto) + ") - Outros: " + str(cont_outro) + "(" + to_human_size(size_outro) + ")")

    def do_monta_lista_arquivos_copiar(self):
        resp = []
        path_base = self.edit_origem.get_text()
            
        for row in self.store:
            if row[0]:
                resp.append(path_base + os.sep + row[2])
        return resp

    def is_video(self, arquivo):
        for ext in get_app_settings("extensoes_video").split('|'):
            if arquivo.lower().endswith(ext.lower()):
                return True
        return False

    def is_foto(self, arquivo):
        for ext in get_app_settings("extensoes_foto").split('|'):
            if arquivo.lower().endswith(ext.lower()):
                return True
        return False

    def do_obter_lista_fotos(self, videos):
        resp = []
        for arquivo in videos:
            if self.is_foto(arquivo):
                resp.append(arquivo)
        return resp

    def do_obter_lista_videos(self, arquivos):
        resp = []
        for arquivo in arquivos:
            if self.is_video(arquivo):
                resp.append(arquivo)
        return resp

    def do_click_mapeamento_dir(self, widget):  # @UnusedVariable
        debug("Mapeamento de diretórios")

        global g_dic_mapeamento_dir_origem
        g_dic_mapeamento_dir_origem = {}
        
        global g_dic_mapeamento_dir_destino
        g_dic_mapeamento_dir_destino = {} 
 
        for arquivo in self.do_monta_lista_arquivos_copiar():
            destino = os.path.dirname(get_destino_arquivo(arquivo))
            g_dic_mapeamento_dir_destino[destino] = destino
            g_dic_mapeamento_dir_origem[destino] = os.path.basename(os.path.dirname(arquivo)) 
        
        if MapeamentoDialog(main_window).show_and_update_file_list():
            self.do_monta_lista_arquivos()

    def do_click_sync_files(self, widget):  # @UnusedVariable
        debug("Montando a lista dos arquivos que serão copiados")

        # Recupera a lista de arquivos selecionados
        arquivos = self.do_monta_lista_arquivos_copiar()

        # Filtra apenas videos e fotos
        if 'True' == get_app_settings("apenas_fotos_e_videos"):
            debug("Filtrando apenas videos e fotos")
            medias = self.do_obter_lista_fotos(arquivos)
            medias.extend(self.do_obter_lista_videos(arquivos))
            arquivos = medias

        debug("Iniciando a cópia dos arquivos")
        # Efetua a cópia dos arquivos
        dialog_arquivos = FileCopyProgressDialog(main_window, arquivos, self.edit_destino.get_text())
        dialog_arquivos.run()
        dialog_arquivos.must_stop = True
        if dialog_arquivos.failed:
            show_message("Falha na cópia dos arquivos!", "Ocorreram falhas durante a cópia de pelo menos um arquivo, verifique o log para mais informações.")

        dialog_arquivos.destroy()
        debug("Cópia dos arquivos finalizada")

        # Verifica se deve recomprimir os videos
        if 'True' == get_app_settings("recodificar_videos"):
            debug("Montando a lista de videos a serem compactados")
            arquivos = self.do_obter_lista_videos(arquivos)
            if len(arquivos) > 0:
                debug("Compactando " + str(len(arquivos)) + " video(s).")

                # Salva o STDOUT para o caso do ffmpeg ser interrompido
                saved_stdout = sys.stdout

                # Efetua a cópia dos arquivos
                dialog_video = VideoEncodeProgressDialog(main_window, arquivos, self.edit_destino.get_text(),)
                dialog_video.run()
                # Força a interrupção da conversão caso o usuário pressione cancel
                dialog_video.must_stop = True
                if dialog_video.failed:
                    show_message("Falha na conversão!", "Ocorreram falhas durante a conversão de pelo menos uma video, verifique o log para mais informações.")

                global g_processo_ffmpeg
                if g_processo_ffmpeg is not None:
                    try:
                        g_processo_ffmpeg.kill()
                        debug("O processo do ffmpeg foi interrompido pelo usuário.")
                    except OSError:
                        debug("O processo do ffmpeg foi finalizado com sucesso.")

                dialog_video.destroy()
                debug("Codificação dos vídeos finalizada")

                # Retorna o STDOUT original
                sys.stdout = saved_stdout

        show_message("Concluído!", "Operação de cópia dos arquivos finalizada!")

    def do_click_config(self, widget):  # @UnusedVariable
        debug("Configurando a aplicação")
        ConfigDialog(main_window).show_and_get_info()

    def do_click_logs(self, widget):  # @UnusedVariable
        debug("Visualizando os logs")
        LogViewerDialog(main_window).show_and_get_info()

    def do_click_close(self, widget):  # @UnusedVariable
        on_close(None, None)

    def on_tree_double_clicked(self, widget, row, col):  # @UnusedVariable
        debug("Duplo click na lista de arquivos (" + str(row) + "," + str(col.get_sort_column_id()) + ")")
        select = self.treeview.get_selection()
        model, treeiter = select.get_selected()
        self.store.set_value(treeiter, 0, not model[treeiter][0])
        self.do_atualiza_contador_selecao()

    def get_file_info(self, arquivo):
    
        captureInfo = 'True' == get_app_settings("exibir_resolucao_arquivos")
    
        if not captureInfo or not self.is_foto(arquivo) and not self.is_video(arquivo):
            return ""

        pattern = re.compile("(Duration: [0-9]{2,}:[0-9]{2,}:[0-9]{2,})|(Video: [^\s]+)|([0-9]{2,}x[0-9]{2,})|([0-9|.]+ fps)|(Audio: [^\s]+)|([0-9]+ Hz)")
        args = [get_caminho_ffmpeg(), "-hide_banner", "-i", arquivo]

        global g_processo_ffmpeg
        g_processo_ffmpeg = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

        lines = ""
        # Inicia o processo e concatena as linhas do output
        for line in iter(g_processo_ffmpeg.stdout.readline, ''):

            # Considera apenas as linhas essenciais
            if line.find("Stream #0") or line.find(" Duration:"):
                lines = lines + line

        if "Duration: 00:00:00" in lines:
            lines = lines.replace("Duration: 00:00:00", "")
            lines = lines.replace("Video: ", "")

        # Recupera o texto dos grupos da regex
        resp = ""
        for m in pattern.finditer(lines):
            resp = resp + m.group() + " "

        # Finaliza o processo do ffmpeg
        g_processo_ffmpeg.stdout.close()
        g_processo_ffmpeg.wait()

        return resp


def get_destino_arquivo(arquivo):
    global g_dic_mapeamento_dir_destino

    g_dic_mapeamento_dir_destino = {} if g_dic_mapeamento_dir_destino is None else g_dic_mapeamento_dir_destino 
    
    nome = os.path.basename(arquivo)
    data = datetime.datetime.fromtimestamp(os.path.getmtime(arquivo))

    # Destino: /YYYY/yyyy-MM-dd/arquivo
    destino = str(data.year) + os.sep + str(data.year) + "-" + str(data.month).zfill(2) + "-" + str(data.day).zfill(2)

    if destino in g_dic_mapeamento_dir_destino:
        destino = g_dic_mapeamento_dir_destino[destino]
    
    return destino + os.sep + nome


def create_icon_and_label_button(label, icon):
    """
    Cria um botão com um ícone e um texto
    """
    
    debug("Criando botão: " + label)
    button = Gtk.Button.new()
    grid = Gtk.Grid()
    grid.set_column_spacing(6)
    grid.attach(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR), 0, 0, 1, 1)
    grid.attach(Gtk.Label(label=label, halign=Gtk.Align.CENTER), 1, 0, 1, 1)
    grid.show_all()
    button.add(grid)
    return button


def compareTreeItem(model, row1, row2, user_data):  # @UnusedVariable
    """
    Compara 2 ítens de uma tree
    """
    
    sort_column, _ = model.get_sort_column_id()
    value1 = model.get_value(row1, sort_column)
    value2 = model.get_value(row2, sort_column)

    if value1 < value2:
        return -1
    elif value1 == value2:
        return 0
    else:
        return 1


def show_message(titulo, msg):
    """
    Exibe um Dialog de aviso
    """

    debug("Exibindo dialog: " + titulo + " - " + msg)
    global main_window
    dialog = Gtk.MessageDialog(main_window, 0, Gtk.MessageType.INFO, Gtk.ButtonsType.CLOSE, titulo)
    dialog.format_secondary_text(msg)
    dialog.run()
    dialog.destroy()
    return None


def indent_xml(elem, level=0):
    """
    Formata um arquivo XML
    """
    
    i = "\n" + level * "\t"
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "\t"
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent_xml(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def set_app_settings(xml_tag, value):
    """
    Salva uma configuração da aplicação
    """

    debug("Salvando configuração da aplicação: " + xml_tag + " = " + value)
    if not os.path.isfile(ARQUIVO_XML_SETTINGS):
        indent_and_save_xml(ET.Element('config'), ARQUIVO_XML_SETTINGS)

    config_tree = ET.parse(ARQUIVO_XML_SETTINGS, ET.XMLParser(remove_comments=False, strip_cdata=False))
    root = config_tree.getroot()

    # Remove o nó se já existir
    if config_tree.find("./" + xml_tag) is not None:
        root.remove(config_tree.find("./" + xml_tag))

    # Se o valor não for nulo, adicionar o novo nó
    if value is not None and value.strip():
        ET.SubElement(root, xml_tag).text = value

    indent_and_save_xml(config_tree.getroot(), ARQUIVO_XML_SETTINGS)


def get_app_settings(xml_tag):
    """
    Recupera uma configuração da aplicação
    """
    
    node_caminho = ET.parse(ARQUIVO_XML_SETTINGS, ET.XMLParser(remove_comments=False, strip_cdata=False)).find("./" + xml_tag)
    return None if node_caminho is None else node_caminho.text


def indent_and_save_xml(root_node, arquivo_xml):
    """
    Formata e salva um arquivo XML
    """

    debug("Salvando o arquivo XML: " + arquivo_xml)
    indent_xml(root_node)
    pretty_xml = ET.tostring(root_node, encoding="UTF-8", method="xml", xml_declaration=True)
    arquivo = open(arquivo_xml, "wb")
    arquivo.write(pretty_xml)
    arquivo.close()


def debug(msg=''):
    """
    Loga uma mensagem
    """
    
    try:
        linha = str(msg).strip()
    except (UnicodeEncodeError):
        linha = msg.encode("utf-8").strip()

    g_logger.debug(linha)


def to_human_size(nbytes):
    """
    Converte uma quantidade de bytes em formato de fácil visualização
    """
    
    human = nbytes
    rank = 0
    if nbytes != 0:
        rank = int((math.log10(nbytes)) / 3)
        rank = min(rank, len(UNIDADES) - 1)
        human = nbytes / (1024.0 ** rank)
    f = ('%.2f' % human).rstrip('0').rstrip('.')
    return '%s %s' % (f, UNIDADES[rank])


def on_close(self, widget):  # @UnusedVariable
    """
    Fecha a aplicação, liberando o FileHandler do log
    """
    
    logHandler.close()
    g_logger.removeHandler(logHandler)
    sys.exit()


def get_codec_info(codec):
    """
    Recupera os parâmtros do ffmpeg para conversão
    """

    resp = None
    if VIDEO_H265 == codec:
        resp = {"params":["-c:v", "libx265", "-acodec", "aac", "-strict", "-2"], "sufixo":"_H265.mp4"}
    elif VIDEO_H264 == codec:
        resp = {"params":["-c:v", "libx264", "-acodec", "aac", "-strict", "-2"], "sufixo":"_H264.mp4"}
    elif VIDEO_VP8 == codec:
        resp = {"params":["-c:v", "libvpx", "-b:v", "1M", "-c:a", "libvorbis"], "sufixo":"_VP8.webm"}
    elif VIDEO_VP9 == codec:
        resp = {"params":["-c:v", "libvpx-vp9", "-b:v", "2M", "-c:a", "libopus"], "sufixo":"_VP9.webm"}
    return resp


def get_caminho_ffmpeg():
    """
    Recupera o caminho onde o ffmpeg está instalado
    """
    
    app = get_app_settings("caminho_ffmpeg")
    return app if app is not None else "ffmpeg"


def get_ffmpeg_features():
    
    """
    Recupera uma lista com as features do ffmpeg: Ex: --enable-libx264
    """
    global g_lista_ffmpeg_features

    if g_lista_ffmpeg_features is None:
        g_processo_ffmpeg = subprocess.Popen([get_caminho_ffmpeg()], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

        linhas = ""
        for line in iter(g_processo_ffmpeg.stdout.readline, ''):
            if "--" in line:
                linhas = linhas + line

        g_processo_ffmpeg.stdout.close()
        g_processo_ffmpeg.wait()

        g_lista_ffmpeg_features = []
        pattern = re.compile("--enable-[^\s]+|disable-[^\s]+")
        for m in pattern.finditer(linhas):
            g_lista_ffmpeg_features.append(m.group())

    return g_lista_ffmpeg_features

# Constantes da aplicação


VERSAO_APPLICACAO = "v1.0"  #  Versão da aplicação


UNIDADES = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']  # Unidades de conversão bytes -> Si
DIR_APPLICATION = os.path.dirname(os.path.realpath(__file__))  # Diretório da aplicação
ARQUIVO_XML_SETTINGS = DIR_APPLICATION + os.sep + "settings.xml"  # Arquivo de configuração da aplicação
ARQUIVO_LOG = DIR_APPLICATION + os.sep + "application.log"  # Arquivo de log

# Codecs de Video
VIDEO_H265 = "Video H265"
VIDEO_H264 = "Video H264"
VIDEO_VP8 = "Video VP8"
VIDEO_VP9 = "Video VP9"
CODECS_VIDEO = []

# Variáveis globais da aplicação
# Nota: por convenção, as variáveis globais são camelCase e iniciam com um 'g' 

g_debug_mode = False  # True para exibir mensagens de debug

# Controle do ffmpeg
g_processo_ffmpeg = None  # Representa a instância do processo do ffmpeg
g_lista_ffmpeg_features = None  # Dicionário com as features de compilação do ffmpeg

# Variáveis dos arquivos de origem
g_leitura_origem_finalizada = False  # Sinaliza o fim da thread de leitura de arquivos de origem 
g_lista_arquivos_origem = None  # Lista de arquivos no diretório de origem
g_dic_info_arquivos_origem = None  # Dicionário com informações sobre os arquivos

# Variáveis dos arquivos de destino
g_leitura_destino_finalizada = False  # Sinaliza o fim da thread de leitura de arquivos de destino
g_lista_arquivos_destino = None  # Lista de arquivos no diretório de destino
g_dic_mapeamento_dir_destino = {}  # Mapeamento dos diretórios de destino
g_dic_mapeamento_dir_origem = {}  # Mapeamento dos diretórios de origem

# Remove o arquivo de log anterior e cria o g_logger
if os.path.isfile(ARQUIVO_LOG):
    os.remove(ARQUIVO_LOG)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(message)s')
logHandler = logging.FileHandler(ARQUIVO_LOG)

g_logger = logging.getLogger('-')  # Logger da aplicação
g_logger.addHandler(logHandler)

# Lê os parâmetros da aplicação
try:
    opts, args = getopt.getopt(sys.argv[1:], "h", [])
except getopt.GetoptError:
    print('photosync.py -h (help)')
    sys.exit(2)
for opt, arg in opts:
    if opt == '-h':
        print("\nPrograma para sincronização de arquivos")
        print("\nUso: photosync.py -h (help)")
        print("\nExemplo: ./photosync.py")
        sys.exit()

# Força UTF-8 por padrão
if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding("utf-8")

if not os.path.isfile(ARQUIVO_XML_SETTINGS):
    set_app_settings("dir_destino", str(os.path.expanduser('~')))
    set_app_settings("dir_origem", str(os.path.expanduser('~')))
    set_app_settings("extensoes_video", "wmv|avi|mpg|3gp|mov|m4v|mts|mp4")
    set_app_settings("extensoes_foto", "dof|arw|raw|jpg|jpeg|png|nef")
    set_app_settings("codec_video", "0")
    set_app_settings("caminho_ffmpeg", "ffmpeg")

main_window = MainWindow()

# Verifica a presença do ffmpeg
if not spawn.find_executable(get_caminho_ffmpeg()):
    info = InputDialog(main_window, 'Informe o caminho para o ffmpeg', '', None).show_and_get_info()
    if info is None or not spawn.find_executable(info):
        print("Não foi possível encontrar o aplicativo necessário ffmpeg.")
        print("Verifique a configuração do caminho do ffmpeg no arquivo settings.xml")
        print("A configuração atual é: " + get_caminho_ffmpeg())
        sys.exit(2)
    else:
        set_app_settings("caminho_ffmpeg", info)

# Exibe as aopções de codec de acordo com a disponibilidade do ffmpeg
if "--enable-libx264" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_H264)

if "--enable-libx265" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_H265)

if "--enable-libvpx" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_VP8)
    CODECS_VIDEO.append(VIDEO_VP9)

# Calling GObject.threads_init() is not needed for PyGObject 3.10.2+
GObject.threads_init()

# Monta a UI
main_window.connect('delete-event', on_close)
main_window.show_all()
Gtk.main()
